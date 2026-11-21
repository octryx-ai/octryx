import { OctryxLogo } from "../chat/companion/OctryxLogo";

/** The Octryx mark at a fixed size (the platform's logo in the text colour). */
export function OctryxMark({ size = 28 }: { size?: number }) {
  return (
    <span className="m-mark" style={{ width: size, height: size }}>
      <OctryxLogo className="m-mark-svg" />
    </span>
  );
}
