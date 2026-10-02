"""Browser real-time testing over WebRTC: a LiveKit room whose join token also dispatches the voice agent."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from nexa.core.config import get_settings
from nexa.providers.telephony.livekit_sip import AGENT_NAME


def browser_test_room(identity: str, metadata: dict[str, Any]) -> dict[str, str]:
    from livekit import api

    s = get_settings()
    room = f"web-test-{uuid.uuid4().hex[:12]}"
    token = (
        api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
        .with_identity(identity)
        .with_name("Browser tester")
        .with_ttl(timedelta(hours=1))
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        # Joining with this token creates the room and dispatches the Nexa voice agent into it.
        .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME,
                                                                             metadata=json.dumps(metadata))]))
        .to_jwt()
    )
    return {"url": s.livekit_public_url, "token": token, "room": room}
