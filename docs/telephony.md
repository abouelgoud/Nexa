# Phone numbers and real-time calls

## Browser (WebRTC)
`Agents → Testing → Real-time (WebRTC)` calls `POST /test/realtime`, which returns a LiveKit token whose room
configuration dispatches the `nexa-voice` worker. Requires the `livekit` and `voice-runtime` services
(`docker compose up`). The push-to-talk/text mode works without LiveKit.

## Real phone numbers
1. Get a number from a SIP carrier (Twilio Elastic SIP Trunking, Telnyx, Plivo, …).
2. Run LiveKit SIP (`docker compose --profile sip up`) on a host with a public IP; open UDP/TCP 5060 and RTP
   10000-10100 (or use LiveKit Cloud and set `LIVEKIT_*`).
3. Point the carrier's origination (inbound) URI to `sip:<your-host>:5060`.
4. In Nexa: `Agents → Phone → Connect a number`. This calls `SIPProvider.register_number`, which creates a LiveKit
   inbound trunk for the number and a dispatch rule (room per call) that dispatches `nexa-voice` with the tenant and
   agent ids. Test numbers use the latest test snapshot when nothing is published; production numbers always use
   the published version.
5. Call the number from your mobile. Inspect the call afterwards under **Calls**.

Outbound test calls ("Have the agent call me") need an outbound trunk (carrier termination URI + credentials) on
the number.

Transfers use SIP REFER (`SIPProvider.transfer`) after the agent finishes its sentence. The provider abstraction
lets Twilio/Telnyx/Plivo-native integrations be added without changing the runtime.
