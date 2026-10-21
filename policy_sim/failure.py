"""Single owner of failure semantics: what happens when an actor stumbles.

The official platform treats model-quality stumbles (exhausted loops, invalid
tool calls, malformed memories) as normal noise: it isolates, degrades and
continues — see AgentBase.run_react_loop's fallback contract. Technical
failures (transport, metering, evidence integrity) stop the run and preserve
the scene. This module is the ONE place that decision is documented and the
ONE source of the recorded outcome; call sites that used to raise on their
own now settle through here.

Classification is made where the failure's origin is known, never by
exception type alone:

- PolicyOfficer.step: a turn that ends without submit+finish (loop exhausted,
  premature finish, invalid calls) settles as an UNFILED round for that actor.
  The official fallback memory still runs; the world advances with the rest.
- driver/_validate_result: ModelClientError and anything escaping the officer
  (checkpoint I/O, transport, evidence) is TECHNICAL → stop new requests,
  drain in-flight, preserve evidence.
- Memory consolidation follows the official runtime (degrade and coerce);
  there is no submit-order gate on it.

Research integrity is preserved because an unfiled round is recorded as the
fact it is — the actor did not transact this round — never fabricated as a
wait or a business action.
"""

WOBBLE_OUTCOME = {"status": "unfiled", "code": "actor_turn_failed"}


def unfiled_receipt(actor_id, round):
    """The authoritative receipt recorded for an actor's unfiled round."""
    return {"actor_id": actor_id, "round": round, **WOBBLE_OUTCOME}
