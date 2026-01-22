/**
 * Clarvis Sprite Definitions
 *
 * Each sprite is a 32x32 pixel grid defined as a 2D array of color strings.
 * Colors are RGBA: "R, G, B, A" (0-255 each)
 *
 * Easy to edit: just change the color variables or pixel patterns!
 */

// =============================================================================
// COLOR PALETTES
// =============================================================================

// Transparent
const _ = "0, 0, 0, 0";

// Thinking state (yellow/amber)
const TH = {
  dark:   "180, 130, 20, 255",   // Dark amber border
  main:   "255, 200, 60, 255",   // Main yellow
  light:  "255, 230, 140, 255",  // Highlight
  eye:    "120, 80, 20, 255",    // Eye color
  bg:     "255, 220, 100, 180",  // Glow background
};

// Running state (green)
const RN = {
  dark:   "30, 120, 60, 255",    // Dark green border
  main:   "60, 200, 100, 255",   // Main green
  light:  "140, 255, 180, 255",  // Highlight
  eye:    "20, 80, 40, 255",     // Eye color
  bg:     "100, 255, 150, 180",  // Glow background
};

// Awaiting state (blue)
const AW = {
  dark:   "40, 80, 160, 255",    // Dark blue border
  main:   "80, 140, 220, 255",   // Main blue
  light:  "160, 200, 255, 255",  // Highlight
  eye:    "30, 60, 120, 255",    // Eye color
  bg:     "120, 180, 255, 180",  // Glow background
};

// Resting state (gray)
const RS = {
  dark:   "80, 80, 90, 255",     // Dark gray border
  main:   "140, 140, 150, 255",  // Main gray
  light:  "180, 180, 190, 255",  // Highlight
  eye:    "60, 60, 70, 255",     // Eye color
  bg:     "160, 160, 170, 120",  // Glow background
};

// Common colors
const WHITE = "255, 255, 255, 255";
const BLACK = "40, 40, 50, 255";

// =============================================================================
// SPRITE BUILDER HELPERS
// =============================================================================

/**
 * Build a sprite frame with the given palette
 * This creates the base robot face - eyes and mouth vary by frame
 */
function buildBaseSprite(p, eyeLeft, eyeRight, mouth) {
  const D = p.dark;
  const M = p.main;
  const L = p.light;
  const E = p.eye;

  // 32x32 robot face
  return [
    //0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    [_,_,_,_,_,_,_,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,_,_,_,_,_,_,_], // 0
    [_,_,_,_,_,D,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,D,_,_,_,_,_], // 1
    [_,_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_,_], // 2
    [_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_], // 3
    [_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_], // 4
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_], // 5
    [_,D,M,M,M,L,L,L,L,L,M,M,M,M,M,M,M,M,M,M,M,M,L,L,L,L,L,M,M,M,D,_], // 6
    [D,M,M,M,L,L,L,L,L,L,L,M,M,M,M,M,M,M,M,M,M,L,L,L,L,L,L,L,M,M,M,D], // 7
    [D,M,M,M,L,...eyeLeft,L,M,M,M,M,M,M,M,M,M,M,L,...eyeRight,L,M,M,M,D], // 8
    [D,M,M,M,L,...eyeLeft,L,M,M,M,M,M,M,M,M,M,M,L,...eyeRight,L,M,M,M,D], // 9
    [D,M,M,M,L,...eyeLeft,L,M,M,M,M,M,M,M,M,M,M,L,...eyeRight,L,M,M,M,D], // 10
    [D,M,M,M,L,L,L,L,L,L,L,M,M,M,M,M,M,M,M,M,M,L,L,L,L,L,L,L,M,M,M,D], // 11
    [D,M,M,M,M,L,L,L,L,L,M,M,M,M,M,M,M,M,M,M,M,M,L,L,L,L,L,M,M,M,M,D], // 12
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_], // 13
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_], // 14
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_], // 15
    [_,D,M,M,M,M,M,M,M,M,M,M,...mouth,M,M,M,M,M,M,M,M,M,M,D,_], // 16
    [_,D,M,M,M,M,M,M,M,M,M,M,...mouth,M,M,M,M,M,M,M,M,M,M,D,_], // 17
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_], // 18
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_], // 19
    [_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_], // 20
    [_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_], // 21
    [_,_,_,D,M,M,M,D,D,D,M,M,M,D,D,D,D,D,D,M,M,M,D,D,D,M,M,M,D,_,_,_], // 22 - indicator dots
    [_,_,_,D,M,M,M,D,L,D,M,M,M,D,L,D,D,L,D,M,M,M,D,L,D,M,M,M,D,_,_,_], // 23
    [_,_,_,D,M,M,M,D,D,D,M,M,M,D,D,D,D,D,D,M,M,M,D,D,D,M,M,M,D,_,_,_], // 24
    [_,_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_,_], // 25
    [_,_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_,_], // 26
    [_,_,_,_,_,D,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,D,_,_,_,_,_], // 27
    [_,_,_,_,_,_,_,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,_,_,_,_,_,_,_], // 28
    [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_], // 29
    [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_], // 30
    [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_], // 31
  ];
}

// =============================================================================
// EYE PATTERNS (5 pixels wide for each eye)
// =============================================================================

function eyes(p, type) {
  const E = p.eye;
  const L = p.light;
  const W = WHITE;

  switch(type) {
    case 'open':      // Wide open - running
      return [[W,W,E,W,W], [W,E,E,E,W], [W,W,E,W,W]];
    case 'half':      // Half closed - thinking
      return [[L,L,L,L,L], [W,W,E,W,W], [W,E,E,E,W]];
    case 'closed':    // Closed - resting
      return [[L,L,L,L,L], [L,L,L,L,L], [E,E,E,E,E]];
    case 'question':  // Question mark - awaiting
      return [[E,E,E,E,L], [L,L,E,L,L], [L,L,E,L,L]];
    case 'look_up':   // Looking up - thinking variation
      return [[W,E,E,E,W], [W,W,W,W,W], [L,L,L,L,L]];
    case 'blink':     // Blinking
      return [[L,L,L,L,L], [E,E,E,E,E], [L,L,L,L,L]];
    default:
      return [[W,W,E,W,W], [W,E,E,E,W], [W,W,E,W,W]];
  }
}

// =============================================================================
// MOUTH PATTERNS (8 pixels wide)
// =============================================================================

function mouth(p, type) {
  const E = p.eye;  // Use eye color for mouth
  const M = p.main;

  switch(type) {
    case 'smile':     // Happy - running
      return [[M,E,M,M,M,M,E,M], [M,M,E,E,E,E,M,M]];
    case 'wavy':      // Wavy - thinking
      return [[M,E,M,M,E,M,M,E], [E,M,E,E,M,E,E,M]];
    case 'neutral':   // Neutral line - resting
      return [[M,M,M,M,M,M,M,M], [M,E,E,E,E,E,E,M]];
    case 'dot':       // Small dot - awaiting
      return [[M,M,M,M,M,M,M,M], [M,M,M,E,E,M,M,M]];
    case 'open':      // Open mouth - surprised
      return [[M,M,E,E,E,E,M,M], [M,M,E,M,M,E,M,M]];
    default:
      return [[M,M,M,M,M,M,M,M], [M,E,E,E,E,E,E,M]];
  }
}

// =============================================================================
// SPRITE FRAMES FOR EACH STATE
// =============================================================================

// Helper to construct a complete sprite
function makeSprite(palette, eyeType, mouthType) {
  const eyePattern = eyes(palette, eyeType);
  const mouthPattern = mouth(palette, mouthType);

  const E = palette.eye;
  const L = palette.light;
  const M = palette.main;
  const D = palette.dark;

  // Build the 32x32 sprite manually with embedded eyes and mouth
  return [
    [_,_,_,_,_,_,_,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,_,_,_,_,_,_,_],
    [_,_,_,_,_,D,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,D,_,_,_,_,_],
    [_,_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_,_],
    [_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_],
    [_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_],
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_],
    [_,D,M,M,M,L,L,L,L,L,L,L,M,M,M,M,M,M,M,M,L,L,L,L,L,L,L,M,M,M,D,_],
    [D,M,M,M,L,L,L,L,L,L,L,L,L,M,M,M,M,M,M,L,L,L,L,L,L,L,L,L,M,M,M,D],
    [D,M,M,M,L,L,L,...eyePattern[0],L,L,M,M,M,M,M,M,L,L,...eyePattern[0],L,L,L,M,M,M,D],
    [D,M,M,M,L,L,L,...eyePattern[1],L,L,M,M,M,M,M,M,L,L,...eyePattern[1],L,L,L,M,M,M,D],
    [D,M,M,M,L,L,L,...eyePattern[2],L,L,M,M,M,M,M,M,L,L,...eyePattern[2],L,L,L,M,M,M,D],
    [D,M,M,M,L,L,L,L,L,L,L,L,L,M,M,M,M,M,M,L,L,L,L,L,L,L,L,L,M,M,M,D],
    [D,M,M,M,M,L,L,L,L,L,L,L,M,M,M,M,M,M,M,M,L,L,L,L,L,L,L,M,M,M,M,D],
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_],
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_],
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_],
    [_,D,M,M,M,M,M,M,M,M,M,M,...mouthPattern[0],M,M,M,M,M,M,M,M,M,M,D,_],
    [_,D,M,M,M,M,M,M,M,M,M,M,...mouthPattern[1],M,M,M,M,M,M,M,M,M,M,D,_],
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_],
    [_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_],
    [_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_],
    [_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_],
    [_,_,_,D,M,M,M,D,D,D,M,M,M,D,D,D,D,D,D,M,M,M,D,D,D,M,M,M,D,_,_,_],
    [_,_,_,D,M,M,M,D,L,D,M,M,M,D,L,D,D,L,D,M,M,M,D,L,D,M,M,M,D,_,_,_],
    [_,_,_,D,M,M,M,D,D,D,M,M,M,D,D,D,D,D,D,M,M,M,D,D,D,M,M,M,D,_,_,_],
    [_,_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_,_],
    [_,_,_,_,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,_,_,_,_],
    [_,_,_,_,_,D,D,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,M,D,D,_,_,_,_,_],
    [_,_,_,_,_,_,_,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,D,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
  ];
}

// =============================================================================
// EXPORTED SPRITE DEFINITIONS
// =============================================================================

const SPRITES = {
  thinking: {
    palette: TH,
    frames: [
      makeSprite(TH, 'half', 'wavy'),
      makeSprite(TH, 'look_up', 'wavy'),
      makeSprite(TH, 'half', 'wavy'),
      makeSprite(TH, 'blink', 'wavy'),
    ],
    fps: 2,
    glow: { pulse: true, speed: 0.02 },
  },

  running: {
    palette: RN,
    frames: [
      makeSprite(RN, 'open', 'smile'),
      makeSprite(RN, 'open', 'smile'),
      makeSprite(RN, 'blink', 'smile'),
    ],
    fps: 4,
    glow: { pulse: false, intensity: 1.0 },
  },

  awaiting: {
    palette: AW,
    frames: [
      makeSprite(AW, 'question', 'dot'),
      makeSprite(AW, 'question', 'dot'),
    ],
    fps: 1,
    glow: { pulse: true, speed: 0.03 },
  },

  resting: {
    palette: RS,
    frames: [
      makeSprite(RS, 'closed', 'neutral'),
    ],
    fps: 0,
    glow: { pulse: true, speed: 0.005 },
  },
};

// Export for use in animator
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { SPRITES, TH, RN, AW, RS };
} else {
  window.SPRITES = SPRITES;
  window.PALETTES = { TH, RN, AW, RS };
}
