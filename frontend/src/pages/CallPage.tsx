import { useSession } from "../lib/useSession";
import { Lobby } from "./Lobby";
import { Queue } from "./Queue";
import { Room } from "./Room";

/** /call: lobby -> queue -> room on one route (the session lives across the phases). */
export function CallPage() {
  const s = useSession();
  const { state } = s;
  switch (state.phase) {
    case "requesting":
    case "queued":
      return <Queue state={state} onCancel={s.cancel} />;
    case "live":
    case "ended":
      if (state.call)
        return (
          <Room
            state={state}
            aiLevel={s.aiLevel}
            onHangup={s.hangup}
            onText={s.sendText}
            onPcm={s.sendPcm}
            onBargeIn={s.bargeIn}
            onAgain={s.reset}
          />
        );
      return <Lobby onJoin={s.join} error={state.error} />;
    default:
      return <Lobby onJoin={s.join} error={state.error} />;
  }
}
