import { useEffect, useState } from "react";

const DESIGN_WIDTH = 1280;
const DESIGN_HEIGHT = 720;

export function useKioskScale() {
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const update = () => {
      const sx = window.innerWidth / DESIGN_WIDTH;
      const sy = window.innerHeight / DESIGN_HEIGHT;
      setScale(Math.min(sx, sy));
    };

    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return scale;
}
