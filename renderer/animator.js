/**
 * Clarvis Animator
 *
 * Handles the 3-layer animation system:
 * - Layer 1: Background glow
 * - Layer 2: Sprite frames (using Data-Pixels)
 * - Layer 3: Particle effects
 */

// =============================================================================
// CONFIGURATION
// =============================================================================

const CONFIG = {
  canvasSize: 160,     // Canvas dimensions (5x scale of 32px sprite)
  pixelSize: 5,        // Each sprite pixel = 5 canvas pixels
  spriteSize: 32,      // Sprite dimensions
  particleCount: 8,    // Max particles per state
};

// =============================================================================
// STATE
// =============================================================================

let currentState = 'resting';
let currentFrame = 0;
let lastFrameTime = 0;
let glowPhase = 0;
let particles = [];
let canvas, ctx;
let dataPixelsCanvas = null;

// =============================================================================
// INITIALIZATION
// =============================================================================

function init() {
  canvas = document.getElementById('clarvis-canvas');
  ctx = canvas.getContext('2d');
  canvas.width = CONFIG.canvasSize;
  canvas.height = CONFIG.canvasSize;

  // Start animation loop
  requestAnimationFrame(animate);

  // Initialize with resting state
  setState('resting');
}

// =============================================================================
// STATE MANAGEMENT (called from Swift via JS bridge)
// =============================================================================

window.setState = function(state, tool) {
  if (!SPRITES[state]) {
    console.warn('Unknown state:', state);
    return;
  }

  const wasState = currentState;
  currentState = state;
  currentFrame = 0;
  lastFrameTime = performance.now();

  // Reset particles on state change
  if (wasState !== state) {
    particles = createParticles(state);
  }

  // Update tool display if provided
  if (tool && window.updateToolName) {
    window.updateToolName(tool);
  }
};

// Expose for testing
window.getState = function() {
  return currentState;
};

// =============================================================================
// MAIN ANIMATION LOOP
// =============================================================================

function animate(timestamp) {
  const sprite = SPRITES[currentState];
  if (!sprite) {
    requestAnimationFrame(animate);
    return;
  }

  // Clear canvas
  ctx.clearRect(0, 0, CONFIG.canvasSize, CONFIG.canvasSize);

  // Layer 1: Background glow
  drawGlow(sprite);

  // Layer 2: Sprite
  drawSprite(sprite, timestamp);

  // Layer 3: Particles
  updateAndDrawParticles(timestamp);

  requestAnimationFrame(animate);
}

// =============================================================================
// LAYER 1: GLOW EFFECT
// =============================================================================

function drawGlow(sprite) {
  const palette = sprite.palette;
  const glow = sprite.glow;

  // Calculate glow intensity
  let intensity = glow.intensity || 0.5;
  if (glow.pulse) {
    glowPhase += glow.speed || 0.02;
    intensity = 0.3 + 0.4 * (0.5 + 0.5 * Math.sin(glowPhase));
  }

  // Parse background color
  const bgColor = palette.bg;
  const [r, g, b, a] = bgColor.split(',').map(s => parseInt(s.trim()));

  // Draw radial gradient glow
  const centerX = CONFIG.canvasSize / 2;
  const centerY = CONFIG.canvasSize / 2;
  const radius = CONFIG.canvasSize * 0.45;

  const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);
  gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${intensity * 0.6})`);
  gradient.addColorStop(0.5, `rgba(${r}, ${g}, ${b}, ${intensity * 0.3})`);
  gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, CONFIG.canvasSize, CONFIG.canvasSize);
}

// =============================================================================
// LAYER 2: SPRITE RENDERING
// =============================================================================

function drawSprite(sprite, timestamp) {
  // Handle frame timing
  const fps = sprite.fps || 1;
  const frameDuration = fps > 0 ? 1000 / fps : Infinity;

  if (timestamp - lastFrameTime >= frameDuration) {
    currentFrame = (currentFrame + 1) % sprite.frames.length;
    lastFrameTime = timestamp;
  }

  const frameData = sprite.frames[currentFrame];

  // Render sprite pixel by pixel
  const offsetX = (CONFIG.canvasSize - CONFIG.spriteSize * CONFIG.pixelSize) / 2;
  const offsetY = (CONFIG.canvasSize - CONFIG.spriteSize * CONFIG.pixelSize) / 2;

  for (let y = 0; y < frameData.length; y++) {
    for (let x = 0; x < frameData[y].length; x++) {
      const color = frameData[y][x];
      if (color && color !== "0, 0, 0, 0") {
        const [r, g, b, a] = color.split(',').map(s => parseInt(s.trim()));
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${(a || 255) / 255})`;
        ctx.fillRect(
          offsetX + x * CONFIG.pixelSize,
          offsetY + y * CONFIG.pixelSize,
          CONFIG.pixelSize,
          CONFIG.pixelSize
        );
      }
    }
  }
}

// =============================================================================
// LAYER 3: PARTICLE SYSTEM
// =============================================================================

function createParticles(state) {
  const particles = [];
  const count = CONFIG.particleCount;

  switch (state) {
    case 'thinking':
      // Floating dots (ellipsis effect)
      for (let i = 0; i < 3; i++) {
        particles.push({
          type: 'dot',
          x: CONFIG.canvasSize * 0.7 + i * 12,
          y: CONFIG.canvasSize * 0.3,
          baseY: CONFIG.canvasSize * 0.3,
          phase: i * Math.PI * 0.5,
          speed: 0.05,
          size: 4,
          color: SPRITES.thinking.palette.dark,
        });
      }
      break;

    case 'running':
      // Sparkles flying off
      for (let i = 0; i < count; i++) {
        particles.push({
          type: 'sparkle',
          x: CONFIG.canvasSize / 2,
          y: CONFIG.canvasSize / 2,
          vx: (Math.random() - 0.5) * 4,
          vy: (Math.random() - 0.5) * 4,
          life: Math.random(),
          maxLife: 1,
          size: 2 + Math.random() * 3,
          color: SPRITES.running.palette.light,
        });
      }
      break;

    case 'awaiting':
      // Floating question marks
      for (let i = 0; i < 2; i++) {
        particles.push({
          type: 'question',
          x: CONFIG.canvasSize * (0.15 + i * 0.7),
          y: CONFIG.canvasSize * 0.8,
          vy: -0.5,
          life: 0,
          maxLife: 2,
          size: 10,
          color: SPRITES.awaiting.palette.dark,
        });
      }
      break;

    case 'resting':
      // Occasional Z's
      particles.push({
        type: 'zzz',
        x: CONFIG.canvasSize * 0.75,
        y: CONFIG.canvasSize * 0.25,
        vy: -0.3,
        vx: 0.2,
        life: 0,
        maxLife: 3,
        size: 8,
        color: SPRITES.resting.palette.dark,
      });
      break;
  }

  return particles;
}

function updateAndDrawParticles(timestamp) {
  const dt = 1 / 60; // Assume 60fps

  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];

    switch (p.type) {
      case 'dot':
        // Bounce up and down
        p.phase += p.speed;
        p.y = p.baseY + Math.sin(p.phase) * 5;
        drawDot(p);
        break;

      case 'sparkle':
        // Move and fade
        p.x += p.vx;
        p.y += p.vy;
        p.life -= dt * 0.5;
        if (p.life <= 0) {
          // Reset sparkle
          p.x = CONFIG.canvasSize / 2 + (Math.random() - 0.5) * 40;
          p.y = CONFIG.canvasSize / 2 + (Math.random() - 0.5) * 40;
          p.vx = (Math.random() - 0.5) * 4;
          p.vy = (Math.random() - 0.5) * 4;
          p.life = p.maxLife;
        }
        drawSparkle(p);
        break;

      case 'question':
        // Float up and respawn
        p.y += p.vy;
        p.life += dt;
        if (p.life >= p.maxLife || p.y < 0) {
          p.y = CONFIG.canvasSize * 0.8;
          p.life = 0;
          p.x = CONFIG.canvasSize * (0.1 + Math.random() * 0.8);
        }
        drawQuestion(p);
        break;

      case 'zzz':
        // Drift up and right
        p.x += p.vx;
        p.y += p.vy;
        p.life += dt;
        if (p.life >= p.maxLife || p.y < 0) {
          p.x = CONFIG.canvasSize * 0.75;
          p.y = CONFIG.canvasSize * 0.25;
          p.life = 0;
        }
        drawZzz(p);
        break;
    }
  }
}

function drawDot(p) {
  const [r, g, b] = p.color.split(',').map(s => parseInt(s.trim()));
  ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
  ctx.beginPath();
  ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
  ctx.fill();
}

function drawSparkle(p) {
  const [r, g, b] = p.color.split(',').map(s => parseInt(s.trim()));
  const alpha = p.life / p.maxLife;
  ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
  ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
}

function drawQuestion(p) {
  const [r, g, b] = p.color.split(',').map(s => parseInt(s.trim()));
  const alpha = Math.min(1, 1 - (p.life / p.maxLife) * 0.5);
  ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
  ctx.font = `bold ${p.size}px monospace`;
  ctx.fillText('?', p.x, p.y);
}

function drawZzz(p) {
  const [r, g, b] = p.color.split(',').map(s => parseInt(s.trim()));
  const alpha = Math.min(1, 1 - (p.life / p.maxLife) * 0.7);
  ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
  ctx.font = `bold ${p.size}px monospace`;
  ctx.fillText('z', p.x, p.y);
}

// =============================================================================
// START
// =============================================================================

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
