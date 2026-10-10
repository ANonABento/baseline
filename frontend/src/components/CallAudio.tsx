// Report call audio: a plain <audio> with a play button, mono clock and a thin scrubber.
// The parent owns the element (via ref) so transcript lines can seek it.
import { useEffect, useState } from "react";
import { fmtTime } from "../analysis";
import type { ReportAudio } from "../lib/contract";

interface Props {
  audio: ReportAudio;
  el: React.RefObject<HTMLAudioElement | null>;
  /** current playback time, s (lifted so the transcript and timeline can follow) */
  time: number;
  onTime: (t: number) => void;
}

export function CallAudio({ audio, el, time, onTime }: Props) {
  const [playing, setPlaying] = useState(false);
  const [dur, setDur] = useState(audio.duration_s);

  // smooth clock while playing (timeupdate alone is ~4 Hz)
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      if (el.current) onTime(el.current.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, el, onTime]);

  const toggle = () => {
    const a = el.current;
    if (!a) return;
    if (a.paused) a.play().catch(() => undefined);
    else a.pause();
  };

  return (
    <div className="player">
      <audio
        ref={el}
        src={audio.url}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
        onSeeked={(e) => onTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration)}
      />
      <button type="button" className="player__btn" onClick={toggle} aria-label={playing ? "Pause call audio" : "Play call audio"}>
        {playing ? "Pause" : "Play"}
      </button>
      <span className="player__clock mono">
        {fmtTime(time)} / {fmtTime(dur)}
      </span>
      <input
        className="player__scrub"
        type="range"
        min={0}
        max={dur || 0}
        step={0.1}
        value={Math.min(time, dur || 0)}
        onChange={(e) => {
          const t = Number(e.target.value);
          if (el.current) el.current.currentTime = t;
          onTime(t);
        }}
        aria-label="Seek call audio"
        aria-valuetext={`${fmtTime(time)} of ${fmtTime(dur)}`}
        style={{ "--p": `${dur ? (Math.min(time, dur) / dur) * 100 : 0}%` } as React.CSSProperties}
      />
      {audio.channels.right == null && <span className="label">Caller audio only</span>}
    </div>
  );
}
