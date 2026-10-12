import { useId } from "react";
import "./badou.css";

/** Display the mascot from the official photograph, without changing the source asset. */
export function BadouMascot({
  animated = false,
  size = "small",
  expression = "smile",
}: {
  expression?: "smile" | "open-eyes";
  animated?: boolean;
  size?: "small" | "large";
}) {
  const clipId = useId();
  return (
    <span
      className={`badou badou--${size}${animated ? " badou--animated" : ""}`}
    >
      <svg
        className="badou-portrait"
        viewBox={
          expression === "open-eyes" ? "362 38 222 132" : "630 30 352 284"
        }
        role="img"
        aria-label="八斗 · 九章云极吉祥物"
        focusable="false"
      >
        <defs>
          <clipPath id={clipId}>
            {expression === "open-eyes" ? (
              <path d="M 369 100 C 377 82 390 78 401 76 C 405 59 414 45 422 46 C 430 50 437 62 440 69 L 500 70 C 505 54 516 44 522 48 C 532 56 537 69 539 79 C 557 83 570 91 576 105 C 580 123 567 147 547 156 C 525 165 501 161 476 155 C 451 166 428 163 407 157 C 381 150 367 129 369 100 Z" />
            ) : (
              <path d="M 688 133 C 692 107 704 85 711 74 C 719 44 728 40 739 48 L 750 57 L 782 49 L 793 48 L 800 45 L 807 52 L 817 49 L 831 58 C 855 48 870 50 877 68 L 885 87 C 908 108 918 129 923 149 C 962 175 980 207 959 244 C 937 282 878 302 817 302 C 751 306 684 287 657 255 C 630 224 647 179 688 133 Z" />
            )}
          </clipPath>
        </defs>
        <image
          href="/brand/badou-official-luckybag.jpg"
          width="1023"
          height="341"
          clipPath={`url(#${clipId})`}
        />
      </svg>
      {animated && <span className="badou-shadow" aria-hidden="true" />}
    </span>
  );
}
