import { useEffect, useState } from "react";

const MOBILE_QUERY = "(max-width: 767px)";

export function useResponsiveListDefault(): boolean {
  // Read the breakpoint synchronously so a phone never renders the graph view for one frame first.
  const [mobile, setMobile] = useState(
    () => typeof window !== "undefined" && Boolean(window.matchMedia?.(MOBILE_QUERY).matches),
  );
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const update = () => setMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return mobile;
}
