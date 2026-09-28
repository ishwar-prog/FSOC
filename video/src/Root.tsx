import { Composition, continueRender, delayRender } from "remotion";

import { INTRO_FRAMES, Intro } from "./Intro";
import { LAUNCH_FRAMES, Launch } from "./launch/Launch";
import { Architecture, Banner, Features, Terminals } from "./stills/Stills";
import { FPS, HEIGHT, WIDTH, loadFonts } from "./theme";

const fontsReady = delayRender("Loading fonts");
loadFonts().then(() => continueRender(fontsReady));

export function RemotionRoot() {
  return (
    <>
      <Composition id="Intro" component={Intro} durationInFrames={INTRO_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="Launch" component={Launch} durationInFrames={LAUNCH_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="Banner" component={Banner} durationInFrames={1} fps={FPS} width={1920} height={560} />
      <Composition id="Features" component={Features} durationInFrames={1} fps={FPS} width={1920} height={900} />
      <Composition id="Terminals" component={Terminals} durationInFrames={1} fps={FPS} width={1920} height={600} />
      <Composition id="Architecture" component={Architecture} durationInFrames={1} fps={FPS} width={1920} height={640} />
    </>
  );
}
