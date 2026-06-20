"""Async HTTP client for the Deferno backend REST API."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from .refs import COMPACT_ITEM_CORE_FIELDS

# During the v0.1 -> v0.2 backend cutover window the MCP server accepts
# either envelope so it doesn't go dark for the hours/days the backend
# takes to flip API_VERSION. Once the backend has settled on "0.2" and a
# rollback to "0.1" is no longer plausible, drop "0.1" from this set.
SUPPORTED_API_VERSIONS: frozenset[str] = frozenset({"0.1", "0.2"})
# Exported so tests (and any future API-negotiation code) can pick the
# "preferred" / latest supported version without depending on the order
# of the frozenset literal.
SUPPORTED_API_VERSION = "0.2"


class DefernoError(RuntimeError):
    """Raised when the Deferno backend returns an error response."""

    def __init__(self, status_code: int, message: str, code: str | None = None) -> None:
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.code = code


class DefernoClient:
    """Thin async wrapper around the Deferno backend API.

    Holds the bearer token in memory. Every request goes through ``_request``
    which raises :class:`DefernoError` on non-2xx responses so tools can
    translate them into readable MCP errors.
    """

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "DefernoClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def token(self) -> str | None:
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        self._token = value

    @property
    def base_url(self) -> str:
        return self._base_url

    async def _ensure_authed(self) -> None:
        if self._token:
            return
        raise DefernoError(
            401,
            "not authenticated — over HTTP, complete the OAuth flow; over "
            "stdio, run `defernowork-mcp auth` in your terminal",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authed: bool = True,
        json_body: Any | None = None,
    ) -> Any:
        headers = {"content-type": "application/json"}
        if authed:
            await self._ensure_authed()
            headers["authorization"] = f"Bearer {self._token}"

        try:
            response = await self._client.request(
                method,
                path,
                headers=headers,
                json=json_body,
            )
        except httpx.TimeoutException:
            raise DefernoError(504, "request timed out")
        except httpx.RequestError as exc:
            raise DefernoError(502, f"network error: {exc}")

        if response.status_code == 204 or not response.content:
            if 200 <= response.status_code < 300:
                return None
            raise DefernoError(response.status_code, response.reason_phrase or "error")

        try:
            payload = response.json()
        except ValueError:
            # Non-JSON body (e.g. HTML error page). Surface raw text.
            raise DefernoError(
                response.status_code,
                response.text or response.reason_phrase or "error",
            )

        # All envelope-versioned responses must be shaped {version, data, error}.
        if not isinstance(payload, dict) or "version" not in payload:
            raise DefernoError(
                502,
                f"backend response missing required 'version' field: {payload!r}",
            )

        version = payload["version"]
        if version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_API_VERSIONS))
            raise DefernoError(
                502,
                f"unsupported API version: {version!r} "
                f"(this client supports {supported})",
            )

        error = payload.get("error")
        if error is not None:
            code = None
            message = response.reason_phrase or "error"
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message", message)
            raise DefernoError(response.status_code, message, code=code)

        if not (200 <= response.status_code < 300):
            # Status is non-2xx but envelope says no error — defensive fallback.
            raise DefernoError(response.status_code, response.reason_phrase or "error")

        return payload.get("data")

    # ------------------------------------------------------------------ auth
    async def oidc_login(self) -> dict[str, Any]:
        """Start an OIDC login flow.

        Returns ``{authorize_url, state}`` — the caller should show
        ``authorize_url`` to the user to open in their browser.
        """
        return await self._request("GET", "/auth/oidc/login", authed=False)

    async def oidc_callback(self, state: str, code: str) -> dict[str, Any]:
        """Exchange an OIDC callback code for a session token.

        Returns ``{token, user}`` or ``{needs_migration, username, oidc_subject}``.
        """
        result = await self._request(
            "GET",
            f"/auth/oidc/callback?state={state}&code={code}",
            authed=False,
        )
        if "token" in result:
            self._token = result["token"]
        return result

    async def cli_init(self) -> dict[str, Any]:
        """Legacy: Start a CLI authentication session."""
        return await self._request("POST", "/auth/cli/init", authed=False)

    async def cli_verify(self, session_id: str, code: str) -> dict[str, Any]:
        """Exchange a CLI auth code for a bearer token.

        Returns ``{token, user}`` and stores the token in ``self._token``.
        """
        result = await self._request(
            "POST",
            "/auth/cli/verify",
            authed=False,
            json_body={"session_id": session_id, "code": code},
        )
        self._token = result["token"]
        return result

    async def register(
        self, username: str, password: str, invite_code: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"username": username, "password": password}
        if invite_code is not None:
            body["invite_code"] = invite_code
        return await self._request("POST", "/auth/register", authed=False, json_body=body)

    async def logout(self) -> None:
        await self._request("POST", "/auth/logout")
        self._token = None

    async def whoami(self) -> dict[str, Any]:
        return await self._request("GET", "/auth/me")

    # ------------------------------------------------------------------ tasks
    async def list_tasks(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/tasks")

    async def search_tasks(
        self,
        query: str,
        *,
        status: str | None = None,
        label: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        parent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"q": query}
        if status is not None:
            params["status"] = status
        if label is not None:
            params["label"] = label
        if from_date is not None:
            params["from"] = from_date
        if to_date is not None:
            params["to"] = to_date
        if parent_id is not None:
            params["parent_id"] = parent_id
        qs = urlencode(params)
        return await self._request("GET", f"/tasks/search?{qs}")

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/tasks/{task_id}")

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/tasks", json_body=payload)

    async def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/tasks/{task_id}", json_body=payload)

    async def split_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/tasks/{task_id}/split", json_body=payload)

    async def merge_task(self, task_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/tasks/{task_id}/merge", json_body={})

    async def fold_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/tasks/{task_id}/fold", json_body=payload)

    async def move_item(
        self, item_id: str, new_parent_id: str | None, position: int | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"new_parent_id": new_parent_id}
        if position is not None:
            body["position"] = position
        return await self._request("POST", f"/items/{item_id}/move", json_body=body)

    async def batch(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", "/tasks/batch", json_body={"operations": operations})

    # -------------------------------------------------------------- daily plan
    async def get_daily_plan(
        self, date: str | None = None, tz: str | None = None
    ) -> list[dict[str, Any]]:
        params: list[str] = []
        if date is not None:
            params.append(f"date={date}")
        if tz is not None:
            params.append(f"tz={quote(tz, safe='')}")
        query = "?" + "&".join(params) if params else ""
        return await self._request("GET", f"/tasks/plan{query}")

    async def mood_history(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/tasks/mood-history")

    async def export_data(self) -> dict[str, Any]:
        """Export all user data."""
        return await self._request("GET", "/tasks/export")

    # ----------------------------------------------------------------- chores
    async def create_chore(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/chores", json_body=payload)

    async def update_chore(self, chore_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/chores/{chore_id}", json_body=payload)

    async def delete_chore(self, chore_id: str) -> None:
        await self._request("DELETE", f"/chores/{chore_id}")

    async def list_chore_occurrences(
        self,
        chore_id: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[str] = []
        if from_date is not None:
            params.append(f"from={from_date}")
        if to_date is not None:
            params.append(f"to={to_date}")
        query = "?" + "&".join(params) if params else ""
        return await self._request("GET", f"/chores/{chore_id}/occurrences{query}")

    async def set_chore_occurrence_status(
        self, chore_id: str, date: str, status: str
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/chores/{chore_id}/occurrences/{date}",
            json_body={"status": status},
        )

    async def mark_next_chore_done(
        self, chore_id: str, status: str = "done"
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/chores/{chore_id}/mark-next-done",
            json_body={"status": status},
        )

    # ----------------------------------------------------------------- habits
    async def create_habit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/habits", json_body=payload)

    async def update_habit(self, habit_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/habits/{habit_id}", json_body=payload)

    async def delete_habit(self, habit_id: str) -> None:
        await self._request("DELETE", f"/habits/{habit_id}")

    async def list_habit_occurrences(
        self,
        habit_id: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[str] = []
        if from_date is not None:
            params.append(f"from={from_date}")
        if to_date is not None:
            params.append(f"to={to_date}")
        query = "?" + "&".join(params) if params else ""
        return await self._request("GET", f"/habits/{habit_id}/occurrences{query}")

    async def mark_habit_occurrence(
        self, habit_id: str, done: bool, date: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"done": done}
        if date is not None:
            body["date"] = date
        return await self._request(
            "POST", f"/habits/{habit_id}/occurrences", json_body=body
        )

    # ----------------------------------------------------------------- events
    async def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/events", json_body=payload)

    async def update_event(self, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/events/{event_id}", json_body=payload)

    async def delete_event(self, event_id: str) -> None:
        await self._request("DELETE", f"/events/{event_id}")

    # ---------------------------------------------------- event occurrences
    async def list_event_occurrences(
        self,
        event_id: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if from_date is not None:
            params["from"] = from_date
        if to_date is not None:
            params["to"] = to_date
        path = f"/events/{event_id}/occurrences"
        if params:
            path = f"{path}?{urlencode(params)}"
        return await self._request("GET", path)

    async def set_event_occurrence(
        self,
        event_id: str,
        date: str,
        action: str,
        cascade_subtasks: bool = False,
    ) -> dict[str, Any]:
        body = {"action": action, "cascade_subtasks": cascade_subtasks}
        return await self._request(
            "POST",
            f"/events/{event_id}/occurrences/{date}",
            json_body=body,
        )

    async def reschedule_event_occurrence(
        self, event_id: str, date: str, new_date: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/events/{event_id}/occurrences/{date}/reschedule",
            json_body={"new_date": new_date},
        )

    # ------------------------------------ event occurrence attachments (PR-F)
    async def presign_event_occurrence_attachments(
        self, event_id: str, date: str, files: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/events/{event_id}/occurrences/{date}/attachments/presign",
            json_body={"files": files},
        )

    async def commit_event_occurrence_attachments(
        self,
        event_id: str,
        date: str,
        intents: list[str] | None = None,
        urls: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {}
        if intents:
            body["intents"] = intents
        if urls:
            body["urls"] = urls
        return await self._request(
            "POST",
            f"/events/{event_id}/occurrences/{date}/attachments",
            json_body=body,
        )

    async def list_event_occurrence_attachments(
        self, event_id: str, date: str
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            f"/events/{event_id}/occurrences/{date}/attachments",
        )

    async def delete_event_occurrence_attachment(
        self, event_id: str, date: str, attachment_id: str
    ) -> None:
        await self._request(
            "DELETE",
            f"/events/{event_id}/occurrences/{date}/attachments/{attachment_id}",
        )

    # ------------------------------------ event occurrence comments (PR-F)
    async def post_event_occurrence_comment(
        self, event_id: str, date: str, body: str, is_private: bool = False
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/events/{event_id}/occurrences/{date}/comment",
            json_body={"body": body, "is_private": is_private},
        )

    async def patch_event_occurrence_comment(
        self,
        event_id: str,
        date: str,
        body: str | None = None,
        is_private: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if is_private is not None:
            payload["is_private"] = is_private
        return await self._request(
            "PATCH",
            f"/events/{event_id}/occurrences/{date}/comment",
            json_body=payload,
        )

    async def delete_event_occurrence_comment(
        self, event_id: str, date: str
    ) -> None:
        await self._request(
            "DELETE",
            f"/events/{event_id}/occurrences/{date}/comment",
        )

    async def reschedule_chore_occurrence(
        self, chore_id: str, date: str, new_date: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/chores/{chore_id}/occurrences/{date}/reschedule",
            json_body={"new_date": new_date},
        )

    async def reschedule_habit_occurrence(
        self, habit_id: str, date: str, new_date: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/habits/{habit_id}/occurrences/{date}/reschedule",
            json_body={"new_date": new_date},
        )

    # --------------------------------------------------------------- comments
    async def update_comment(self, comment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/comments/{comment_id}", json_body=payload)

    async def delete_comment(self, comment_id: str) -> None:
        await self._request("DELETE", f"/comments/{comment_id}")

    # --------------------------------------------------------- saved searches
    async def list_saved_searches(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/saved-searches")

    async def create_saved_search(
        self, name: str, query_string: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/saved-searches",
            json_body={"name": name, "query_string": query_string},
        )

    async def update_saved_search(
        self,
        saved_search_id: str,
        name: str | None = None,
        query_string: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if query_string is not None:
            body["query_string"] = query_string
        return await self._request(
            "PATCH", f"/saved-searches/{saved_search_id}", json_body=body
        )

    async def delete_saved_search(self, saved_search_id: str) -> None:
        await self._request("DELETE", f"/saved-searches/{saved_search_id}")

    async def reorder_saved_searches(self, ids: list[str]) -> dict[str, Any]:
        return await self._request(
            "POST", "/saved-searches/reorder", json_body={"ids": ids}
        )

    # --------------------------------------------------------------- feedback
    async def list_feedback(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/feedback")

    async def feedback_stats(self) -> dict[str, Any]:
        return await self._request("GET", "/feedback/stats")

    async def update_feedback(
        self, feedback_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH", f"/feedback/{feedback_id}", json_body=payload
        )

    # ------------------------------------------------------------------ auth/settings
    async def get_settings(self) -> dict[str, Any]:
        return await self._request("GET", "/auth/me/settings")

    async def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", "/auth/me/settings", json_body=payload)

    # ----------------------------------------------------------------- items
    async def get_item(self, item_id: str) -> dict[str, Any]:
        """Fetch any item kind by UUID (``GET /items/{id}``).

        Returns the flat ItemEnvelope view: the item's own fields plus the
        computed ref fields (``ref``, ``org_slug``, ``sequence``, ``type``)
        and the inner ``kind`` discriminator.
        """
        return await self._request("GET", f"/items/{item_id}")

    async def get_item_by_sequence(self, seq: int | str) -> dict[str, Any]:
        """Resolve a Sequence shorthand to an item (``GET /items/by-seq/{seq}``).

        Personal-org only, by design — the backend ``by-seq`` route resolves
        the sequence against the caller's personal org. Accepts a bare integer
        (``123``); the backend also tolerates the ``#123`` shorthand form.
        """
        return await self._request("GET", f"/items/by-seq/{quote(str(seq), safe='')}")

    async def get_item_by_ref(self, canonical: str) -> dict[str, Any]:
        """Resolve a Canonical ref to an item (``GET /items/by-ref/{canonical}``).

        ``canonical`` is ``{org_slug}-{sequence}`` (e.g. ``acme-123``). The
        backend resolves the org slug globally, so this works across orgs.
        """
        return await self._request(
            "GET", f"/items/by-ref/{quote(canonical, safe='')}"
        )

    async def get_item_by_alias(self, alias: str) -> dict[str, Any]:
        """Resolve an external **Alias** to an item (``GET /items/by-alias/{alias}``).

        ``alias`` is an upstream-tracker identifier — e.g. the unambiguous
        GitHub form ``owner/repo#N``, or an ambiguous string like ``ABC-223``
        forced down the alias path via ``get_item(as_alias=True)``. The alias is
        URL-quoted with ``safe=''`` (mirroring :meth:`get_item_by_ref`), so the
        ``/`` and ``#`` in ``owner/repo#N`` are percent-encoded. Returns the
        resolved item in the same flat ItemEnvelope shape as by-seq / by-ref.

        NOTE: aliases only RESOLVE server-side once Deferno's **External tasks**
        feature ships; the route exists today, so routing + the escape-hatch are
        implementable and testable (mocked) now.
        """
        return await self._request(
            "GET", f"/items/by-alias/{quote(alias, safe='')}"
        )

    async def list_items(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = None,
        full: bool = False,
        window: str | None = None,
    ) -> list[dict[str, Any]]:
        """List items across all kinds via the canonical ``GET /items`` window.

        Builds the OData query the backend's ``list_items`` handler parses:

        - ``$select`` — the compact LIST-row field set (``COMPACT_ITEM_CORE_FIELDS``),
          omitted when ``full`` is set. This is the "shrink at the wire" lever
          (ADR-0002): the backend always re-injects ``id``/``kind`` and the
          envelope fields (``ref``/``org_slug``/``type``/``sequence``) regardless
          of ``$select``, so a narrow select never loses identity.
        - ``$top`` — ``limit`` passed through VERBATIM. The backend caps ``$top``
          at 500 by REJECTING values above it with a 400 (``$top exceeds max of
          500``), NOT by silently clamping; we don't rewrite the caller's number.
        - ``$filter`` — composed with ``and`` from the supplied facets. Field
          names match the backend allowlist: ``kind`` (Task/Habit/Chore/Event,
          NOT ``type``), ``status``, and the date field ``complete_by``.
          ``complete_by`` is a *DateTime* field, and the OData evaluator has no
          Date<->DateTime coercion, so ``from_date``/``to_date`` are widened to
          RFC3339 day boundaries (``ge {d}T00:00:00Z`` / ``le {d}T23:59:59.999Z``)
          — a bare ``YYYY-MM-DD`` would tokenize to a Date literal and match zero
          DateTime rows. This mirrors the webui's ``buildVisibilityFilter``.
        - ``window`` — ``window=all`` opts out of the backend's default
          done-visibility window (full history). The backend only applies that
          default window when there is NO ``$filter`` anyway.

        Returns the backend rows verbatim (the MCP tool layer applies the
        defence-in-depth Compact projection on top).
        """
        params: list[str] = []

        if not full:
            params.append("$select=" + quote(",".join(COMPACT_ITEM_CORE_FIELDS), safe=","))

        clauses: list[str] = []
        if kind is not None:
            clauses.append(f"kind eq '{kind}'")
        if status is not None:
            clauses.append(f"status eq '{status}'")
        if from_date is not None:
            clauses.append(f"complete_by ge {from_date}T00:00:00Z")
        if to_date is not None:
            clauses.append(f"complete_by le {to_date}T23:59:59.999Z")
        if clauses:
            params.append("$filter=" + quote(" and ".join(clauses), safe=""))

        if limit is not None:
            params.append(f"$top={limit}")

        if window is not None:
            params.append(f"window={quote(window, safe='')}")

        query = "?" + "&".join(params) if params else ""
        return await self._request("GET", f"/items{query}")

    async def get_items_calendar(
        self, start: str, end: str, tz: str | None = None
    ) -> list[dict[str, Any]]:
        params = [f"start={start}", f"end={end}"]
        if tz is not None:
            params.append(f"tz={quote(tz, safe='')}")
        query = "?" + "&".join(params)
        return await self._request("GET", f"/items/calendar{query}")

    async def get_items_plan(
        self, date: str | None = None, tz: str | None = None
    ) -> list[dict[str, Any]]:
        params: list[str] = []
        if date is not None:
            params.append(f"date={date}")
        if tz is not None:
            params.append(f"tz={quote(tz, safe='')}")
        query = "?" + "&".join(params) if params else ""
        return await self._request("GET", f"/items/plan{query}")

    async def add_to_items_plan(
        self, task_id: str, date: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"task_id": task_id}
        if date is not None:
            body["date"] = date
        return await self._request("POST", "/items/plan/add", json_body=body)

    async def remove_from_items_plan(
        self, task_id: str, date: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"task_id": task_id}
        if date is not None:
            body["date"] = date
        return await self._request("POST", "/items/plan/remove", json_body=body)

    async def reorder_items_plan(
        self, task_ids: list[str], date: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"task_ids": task_ids}
        if date is not None:
            body["date"] = date
        return await self._request("POST", "/items/plan/reorder", json_body=body)

    # ── item-level activity: kind-neutral comments + attachments (#12) ──────
    #
    # These hit the item-level surface ``/items/{id}/...`` so a Task, Chore, or
    # Habit can be commented on / attached to by id without the caller knowing
    # its kind. ``/items/{id}/comments`` exists today (Task-only until Deferno
    # backend #266 extends it to Chore/Habit); the ``/items/{id}/attachments/*``
    # routes land with Deferno backend #215 (shapes mirror /tasks/{id}/...).
    # Events are rejected by the backend with a 400 — use the per-occurrence
    # comment/attachment methods for Events.

    async def post_item_comment(
        self, item_id: str, body: str, is_private: bool = False
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/items/{item_id}/comments",
            json_body={"body": body, "is_private": is_private},
        )

    async def list_item_comments(self, item_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/items/{item_id}/comments")

    async def presign_item_attachments(
        self, item_id: str, files: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/items/{item_id}/attachments/presign",
            json_body={"files": files},
        )

    async def commit_item_attachments(
        self,
        item_id: str,
        intents: list[str] | None = None,
        urls: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {}
        if intents:
            body["intents"] = intents
        if urls:
            body["urls"] = urls
        return await self._request(
            "POST", f"/items/{item_id}/attachments", json_body=body
        )

    async def list_item_attachments(self, item_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/items/{item_id}/attachments")

    async def delete_item_attachment(self, item_id: str, attachment_id: str) -> None:
        await self._request(
            "DELETE", f"/items/{item_id}/attachments/{attachment_id}"
        )

    async def set_item_attachment_caption(
        self, item_id: str, attachment_id: str, caption: str | None
    ) -> dict[str, Any]:
        # PATCH at the parent path (ADR 2026-05-21-attachment-caption): a string
        # sets/changes the caption, ``null`` clears it. The body always carries
        # ``caption`` (including JSON null) so clearing is unambiguous.
        return await self._request(
            "PATCH",
            f"/items/{item_id}/attachments/{attachment_id}",
            json_body={"caption": caption},
        )

    async def convert_item(
        self, item_id: str, to: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Convert an item to a different kind.

        The wire field is ``to`` (backend ``ConvertItemPayload.to``); the
        gap-closure plan called this ``target_kind`` but the actual backend
        struct uses ``to``. Extra keyword args (``complete_by``, ``end_time``,
        ``recurrence``) are forwarded verbatim and are required by the
        backend when ``to`` is Event/Chore/Habit (see backend payloads.rs).
        Returns the new item view; backend uses 201 on real conversion and
        200 when ``to`` matches the current kind (idempotent).
        """
        body: dict[str, Any] = {"to": to}
        for k, v in kwargs.items():
            if v is not None:
                body[k] = v
        return await self._request(
            "POST", f"/items/{item_id}/convert", json_body=body
        )

    async def get_item_history(self, item_id: str) -> list[dict[str, Any]]:
        """Return the action history list for any item kind."""
        return await self._request("GET", f"/items/{item_id}/history")

    async def set_item_pinned(self, item_id: str, pinned: bool) -> None:
        """Pin or unpin an item. Backend returns 204 NO_CONTENT.

        The plan's optional ``label`` field is not implemented server-side
        (``SetPinnedPayload`` only carries ``pinned``); per-pin labels live
        in the separate ``/tasks/pinned/{id}`` PATCH route (see Task 9).
        """
        await self._request(
            "POST", f"/items/{item_id}/pin", json_body={"pinned": pinned}
        )

    # ----------------------------------------------------------- pinned tasks
    async def list_pinned_tasks(self) -> list[dict[str, Any]]:
        """Return the user's sidebar-pinned items in display order.

        Each entry has the shape ``{task: TaskSummary, label: str | null}``.
        The handler reconciles inconsistencies on every call (drops list
        entries whose underlying task is no longer pinned or has been
        deleted), so the result is always self-consistent.
        """
        return await self._request("GET", "/tasks/pinned")

    async def reorder_pinned_tasks(self, task_ids: list[str]) -> None:
        """Replace the pinned-list ordering with ``task_ids``.

        Wire body is ``{"task_ids": [uuid, ...]}`` — NOT ``ids``. Must be
        an exact permutation of the user's current pinned set; the backend
        rejects sets with extra/missing/duplicate ids with 400. Returns 204.
        """
        await self._request(
            "POST", "/tasks/pinned/reorder", json_body={"task_ids": task_ids}
        )

    async def update_pinned_label(
        self, task_id: str, label: str | None
    ) -> None:
        """Set or clear the custom sidebar label for a pinned task.

        Pass ``label=None`` to clear. The body is sent unconditionally as
        ``{"label": label}`` (including the JSON ``null``) — there is no
        other way to clear a label. Returns 204 on success; 404 if the
        task is not in the user's pinned list.
        """
        await self._request(
            "PATCH",
            f"/tasks/pinned/{task_id}",
            json_body={"label": label},
        )

    # ---------------------------------------------------------- tasks (extras)
    async def delete_task(self, task_id: str) -> None:
        await self._request("DELETE", f"/tasks/{task_id}")

    async def import_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/tasks/import", json_body=payload)

    async def promote_task(self, task_id: str, target_org_id: str) -> None:
        """Promote a personal-org task into ``target_org_id``.

        The caller must own the task in their personal org and be a member
        of ``target_org_id``. The backend re-encrypts the task under the
        target org's DEK. Returns ``None`` (envelope ``data`` is ``null``).
        """
        await self._request(
            "POST",
            f"/tasks/{task_id}/promote",
            json_body={"target_org_id": target_org_id},
        )
