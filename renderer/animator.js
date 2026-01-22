/**
 * Clarvis Renderer - Static sprite, no animation
 */

const CONFIG = {
  pixelSize: 4,  // Each ASCII char = 4x4 canvas pixels
};

let canvas, ctx;

function init() {
  canvas = document.getElementById('clarvis-canvas');
  ctx = canvas.getContext('2d');

  // Set canvas size from sprite
  const height = SPRITE.length;
  const width = Math.max(...SPRITE.map(row => row.length));

  canvas.width = width * CONFIG.pixelSize;
  canvas.height = height * CONFIG.pixelSize;

  // Draw once
  drawSprite();
}

function drawSprite() {
  const px = CONFIG.pixelSize;

  for (let y = 0; y < SPRITE.length; y++) {
    for (let x = 0; x < SPRITE[y].length; x++) {
      const color = SPRITE[y][x];
      if (color && color !== '0, 0, 0, 0') {
        const [r, g, b, a] = color.split(',').map(s => parseInt(s.trim()));
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${(a || 255) / 255})`;
        ctx.fillRect(x * px, y * px, px, px);
      }
    }
  }
}

// For Swift bridge (no-op for now)
window.setState = function(state, tool) {};
window.getState = function() { return 'static'; };

// Start
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
