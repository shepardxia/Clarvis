# Animation Design Guide

Quick reference for creating Clarvis face animations.

## File Structure

```yaml
kind: animation
name: my_animation
# Brief description of the mood/state

sequences:
  sequence_name:
    - frame1
    - frame2

frames:
  - $sequence_name
  - single_frame
```

## The Three Layers

### 1. Component Shorthands
Map readable names to Unicode characters:

```yaml
{ eyes: "open", mouth: "smile", border: "thin" }
# Expands to: { eyes: "◕", mouth: "◡", border: "─" }
```

### 2. Frame Presets
Complete frame definitions by name:

```yaml
- happy           # { eyes: "◕", mouth: "◡", border: "─" }
- focused         # { eyes: "●", mouth: "━", border: "▸", corners: "heavy" }
```

### 3. Sequences
Reusable frame groups with `$name` syntax:

```yaml
sequences:
  blink:
    - { eyes: "half" }
    - { eyes: "closed" }
    - { eyes: "half" }

frames:
  - happy
  - $blink        # Expands to 3 frames
  - happy
```

## Quick Reference

### Eyes
| Shorthand | Char | Use for |
|-----------|------|---------|
| `open` | ◕ | Default, happy |
| `closed` | ─ | Blink, sleep |
| `half` | ◔ | Thinking, drowsy |
| `wide` | ◎ | Surprise, curiosity |
| `dot` | ● | Focus, executing |
| `intense` | ◉ | Deep focus |
| `left` | ◐ | Looking left |
| `right` | ◑ | Looking right |
| `sleepy` | ◡ | Sleeping |
| `sparkle` | ✧ | Joy, eureka |
| `star` | ★ | Celebration |
| `bright` | ✦ | Excitement |

### Mouth
| Shorthand | Char | Use for |
|-----------|------|---------|
| `smile` | ◡ | Happy, content |
| `grin` | ◠ | Very happy |
| `neutral` | ─ | Thinking, reading |
| `flat` | ━ | Focused, serious |
| `open` | ○ | Talking, surprise |
| `sleep` | ω | Sleeping |
| `soft` | ‿ | Gentle smile |
| `hmm` | ∪ | Pondering |
| `frown` | △ | Concern |

### Border
| Shorthand | Char | Use for |
|-----------|------|---------|
| `thin` | ─ | Default, relaxed |
| `medium` | ━ | Active, thinking |
| `thick` | ═ | Intense, important |
| `dotted` | ┉ | Waiting |
| `dotted_sparse` | ┅ | Waiting variation |
| `arrow` | ▸ | Running, executing |
| `arrow_thin` | ▹ | Pulse low |
| `arrow_thick` | ► | Pulse high |
| `sparkle` | ✧ | Creative, writing |
| `star` | ✦ | Celebration |

### Presets
| Name | Description |
|------|-------------|
| `happy` | Default friendly face |
| `neutral` | Calm, observing |
| `thinking` | Looking up, pondering |
| `focused` | Dot eyes, heavy border |
| `intense` | Maximum focus |
| `asleep` | Sleeping peacefully |
| `dreaming` | Sleep with soft smile |
| `surprised` | Wide eyes, open mouth |
| `eureka` | Sparkle eyes, discovery |
| `party` | Star eyes, celebration |
| `sparkle` | Sparkle everything |
| `satisfied` | Content after success |
| `running` | Executing with arrows |
| `waiting` | Dotted border, patient |
| `creating` | Writing with sparkles |
| `pondering` | Deep thought, heavy |

## Design Patterns

### Pattern 1: Base + Variation
Most animations follow: establish base state, add occasional variations.

```yaml
sequences:
  base:
    - happy
    - happy
    - happy

  variation:
    - { eyes: "half", mouth: "smile" }
    - happy

frames:
  - $base
  - $base
  - $variation    # Break the monotony
  - $base
```

### Pattern 2: Gradual Build
Build intensity, then release.

```yaml
sequences:
  calm:
    - { eyes: "open", border: "thin" }

  building:
    - { eyes: "open", border: "medium" }
    - { eyes: "wide", border: "thick" }

  peak:
    - { eyes: "sparkle", border: "star" }

  settle:
    - { eyes: "open", border: "thin" }

frames:
  - $calm
  - $building
  - $peak
  - $settle
```

### Pattern 3: Rhythmic Pulse
Regular rhythm with accent beats.

```yaml
sequences:
  tick:
    - { border: "arrow" }
    - { border: "arrow_thin" }

  tock:
    - { border: "arrow_thick" }
    - { border: "arrow" }

frames:
  - $tick
  - $tick
  - $tock      # Accent
  - $tick
```

### Pattern 4: Scanning/Looking
Eyes move to gather information.

```yaml
sequences:
  look_left:
    - { eyes: "left" }
    - { eyes: "left" }
    - { eyes: "open" }

  look_right:
    - { eyes: "right" }
    - { eyes: "right" }
    - { eyes: "open" }

  center:
    - { eyes: "open" }

frames:
  - $look_left
  - $center
  - $look_right
  - $center
```

### Pattern 5: Blink
Natural blink: half → closed → half → open.

```yaml
sequences:
  blink:
    - { eyes: "half" }
    - { eyes: "closed" }
    - { eyes: "half" }

  rest:
    - happy
    - happy
    - happy
    - happy

frames:
  - $rest
  - $rest
  - $blink     # Blink every ~8 frames
  - $rest
```

## Animation Length Guidelines

At 3 FPS:
- **Short accent** (eureka burst): 6-9 frames (2-3 sec)
- **Standard loop**: 30-45 frames (10-15 sec)
- **Long ambient**: 45-60 frames (15-20 sec)

## Creating a New Animation

1. **Choose the mood**: What emotion/state does this represent?

2. **Pick a base preset**: Start with closest existing preset

3. **Define 2-4 sequences**:
   - `base` or `rest`: The default state (3-4 frames)
   - `variation1`: First type of movement
   - `variation2`: Second type (optional)
   - `accent`: Rare special moment (optional)

4. **Compose frames**: Mix sequences for 30-45 frames total

5. **Test the timing**: At 3 FPS, does it feel right?

### Example: Creating "curious"

```yaml
kind: animation
name: curious
# Inquisitive and exploring

sequences:
  base:
    - { eyes: "open", mouth: "smile", border: "thin" }
    - { eyes: "open", mouth: "smile", border: "thin" }

  tilt_head:
    - { eyes: "half", mouth: "smile", border: "thin" }
    - { eyes: "wide", mouth: "open", border: "thin" }
    - { eyes: "open", mouth: "smile", border: "thin" }

  examine:
    - { eyes: "wide", mouth: "neutral", border: "medium" }
    - { eyes: "wide", mouth: "neutral", border: "medium" }
    - { eyes: "open", mouth: "smile", border: "thin" }

  aha:
    - { eyes: "sparkle", mouth: "grin", border: "star" }
    - { eyes: "open", mouth: "smile", border: "thin" }

frames:
  - $base
  - $base
  - $tilt_head
  - $base
  - $examine
  - $base
  - $base
  - $tilt_head
  - $base
  - $aha        # Occasional discovery
  - $base
```

## Tips

- **Fewer unique frames = smoother feel**: Reuse sequences heavily
- **Border changes = energy level**: thin → calm, thick → intense
- **Eye changes = attention**: where is the avatar looking?
- **Mouth changes = communication**: talking, reacting, resting
- **Heavy corners** signal focus/intensity: `corners: "heavy"`
- **Sparkles are special**: save for celebrations and breakthroughs
