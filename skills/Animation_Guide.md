# Aura.build — Animation Prompting Guide

Source: https://aura.build/learn/animation-prompting

---

## Introduction to Animation

Effective animations provide context, guidance, and feedback to users, making interfaces more intuitive and engaging.

### Key Considerations

1. **Purpose of the animation** — Draw attention, show state change, provide feedback, or guide users through a process?
2. **Animation properties** — Duration, timing function, delay, and intensity all affect the feel.
3. **Trigger events** — Page load, user interaction, scroll position, or state changes?
4. **User experience** — Respect `prefers-reduced-motion`, ensure animations enhance rather than distract.

---

## Text Animation

### Character Reveal
Reveal text character by character, creating a typing effect. Perfect for headers and introductions.
```
Create a typing animation that reveals each character with a 50ms delay
between characters for the main headline.
```

### Word Fade Up
Animate words fading in and moving upward with staggered timing, creating a smooth flowing effect.
```
Create a staggered fade-up animation for each word in the tagline, with 100ms
delay between each word, moving from 10px below to their final position.
```

### Letter by Letter
Each letter appears with a scaling effect, creating a dynamic and playful animation.
```
Create a letter-by-letter animation that reveals each character with a subtle
scale effect and 80ms staggered delay.
```

### Combined Animation
Combines fade, slide, and blur effects letter by letter for a sophisticated entrance.
```
Create a complex animation that fades in, slides up, and reduces blur for each
letter with a 60ms staggered delay between characters.
```

### Gradient Text
Apply animated gradient backgrounds to text for an eye-catching effect.
```
Apply a moving gradient background from blue to purple to the main heading,
with the gradient animating horizontally over 3 seconds in a loop.
```

### Blur Transition
Transition between text blur states for subtle motion effects or loading indication.
```
Create a text transition that blurs from 0 to 5px and back when switching
between content states, with a 400ms transition duration.
```

### Clipped Slide In
Text reveals through a clipping mask while sliding into position.
```
Create a text animation that slides in with a clipping mask effect that reveals
the text from left to right over 800ms with an ease-out timing function.
```

### 3D Transform
Text rotates and transforms in 3D space, creating an immersive depth effect.
```
Apply a 3D transformation to heading text that rotates around the Y-axis with
proper perspective, creating a realistic 3D flip effect with 700ms duration.
```

### Pro Tip
Keep text animations subtle and brief. Ensure animated text remains readable throughout. For longer texts, animate only headings or key phrases rather than entire paragraphs.

---

## Card Animation

### Hover Scale Effect
A subtle scale effect on hover creates a sense of elevation and interactivity.
```
Add a hover effect to product cards that scales them to 1.05x their size and
adds a subtle shadow with a smooth 300ms transition.
```

### Tilt Effect
A 3D tilt effect that follows the cursor creates an immersive, interactive feel.
```
Create a 3D tilt effect for feature cards that responds to cursor position,
with a maximum rotation of 10 degrees and a subtle shadow that shifts with
the tilt angle.
```

### Staggered Entrance
Cards enter the view in sequence creating a dynamic, orchestrated feel.
```
Implement a staggered entrance animation for testimonial cards where each card
fades in and moves up with a 100ms delay between each card.
```

### Flip Card
Flip cards reveal additional information with a 3D rotation effect.
```
Create flip cards that rotate 180 degrees on hover to reveal additional
information on the back side, with a smooth 3D rotation effect.
```

### Card Animation Best Practices
- Keep animations subtle and brief (under 300ms) for hover effects
- Ensure accessibility by not relying solely on hover for critical actions
- Use hardware-accelerated properties like `transform` and `opacity` for smoother animations

---

## Button Animation

### Scale & Color
Combines subtle scale change with color shift for clear feedback.
```
Create a button that scales to 1.05x size and shifts from blue-500 to blue-600
on hover with a 250ms transition.
```

### Ripple Effect
Creates a ripple effect that radiates from the click point.
```
Add a Material Design-inspired ripple effect that expands from the click point
outward with a subtle fade-out animation.
```

### Border Animation
Animated border that moves around the button perimeter.
```
Create a button with an animated border that appears to draw around the button's
perimeter on hover, taking 1 second to complete the animation.
```

### Icon Slide
Text and icon slide into new positions on hover.
```
Create a button where the text slides left and an arrow icon appears from the
right on hover, with a smooth 300ms transition.
```

### Pulse Effect
Pulsing glow effect that draws attention to important actions.
```
Add a pulsing glow effect to the CTA button that expands and fades out
repeatedly to draw attention to important actions.
```

### Loading State
Transitions from text to spinner to indicate processing.
```
Create a button that shows a loading spinner when clicked, with text fading
out and spinner fading in during the loading state.
```

### Button Animation Best Practices
- Keep animations quick (under 300ms) to maintain perceived performance
- Provide immediate visual feedback on click/tap
- Ensure animations don't delay actual functionality or form submission
- For loading states, keep users informed about progress

---

## Alert Animation

### Slide Down Alert
Alert slides down from the top and automatically dismisses.
```
Create a success alert that slides down from the top of the page, remains
visible for 5 seconds, then slides back up and out of view.
```

### Fade & Shake Alert
Alert fades in with a shake animation to draw attention to critical errors.
```
Create an error alert that fades in and shakes horizontally three times to
draw attention to critical errors or warnings.
```

### Toast Notification
Toast slides in from the right with an auto-dismiss progress indicator.
```
Create a toast notification that slides in from the right edge, shows a
progress bar indicating how long until it auto-dismisses, then slides out
to the right.
```

### Stacked Alerts
Multiple alerts stack visually, with newest alerts pushing older ones upward.
```
Create a system for stacked notifications where new alerts appear at the
bottom and push existing alerts upward, with animations for both entrance
and exit.
```

### Alert Animation Best Practices
- Match animation style to alert importance (subtle for info, noticeable for warnings/errors)
- Use auto-dismiss for non-critical alerts, keep error messages visible until acknowledged
- Provide visual indicator of remaining time for auto-dismissing alerts
- Ensure alerts are accessible with appropriate ARIA roles and attributes

---

## Animation Timing

### Easing Functions

| Function | Feel |
|----------|------|
| **Linear** | Constant speed, mechanical |
| **Ease** | Natural, default browser |
| **Ease-in-out** | Smooth acceleration and deceleration |
| **Bounce** | Playful, bouncy ending |

```
Apply an ease-in-out timing function to create smooth, natural movement for
UI elements that slide into view, with acceleration at the start and
deceleration at the end.
```

### Duration Guidelines

| Duration | Use Case |
|----------|----------|
| **Ultra-fast (100ms)** | Micro-interactions |
| **Fast (200-300ms)** | Hover effects, buttons |
| **Medium (400-600ms)** | Modals, alerts |
| **Slow (700ms-1s)** | Page transitions |

```
Use short durations (150-250ms) for button hover effects to maintain
responsiveness, and longer durations (400-500ms) for entrance animations
to create emphasis.
```

### Timing Best Practices
- Match timing function to animation's purpose
- Use shorter durations for small elements and micro-interactions
- Consider user expectation — important actions should feel responsive
- Test on both fast and slow devices
- For complex animations, use easing functions that feel natural

---

## Basic Animation Patterns

| Pattern | Description |
|---------|-------------|
| **Fade In** | Opacity 0 → 1 |
| **Slide In** | Translate from offset to position |
| **Bounce** | Scale with elastic overshoot |
| **Pulse** | Rhythmic scale oscillation |
| **Delayed Animation** | Fade/slide with initial delay |
| **Blur Effect** | Blur → clear transition |
| **Rotate** | Rotation transform |
| **Sequence** | Staggered multi-element animation |

### Performance Tips
Animate only `transform` and `opacity` properties when possible. These are hardware-accelerated and don't trigger layout recalculations. Avoid animating `width`, `height`, or `margin` that cause layout reflows.

---

## Animation Prompt Builder Parameters

### Inputs

1. **Animation Type**: FADE / SLIDE / SCALE / ROTATE / BLUR
2. **Duration**: Fast → Medium → Slow (e.g., 800ms)
3. **Delay**: None → Medium → Long (e.g., 0ms)
4. **Easing Function**: LINEAR / EASE / EASE IN / EASE OUT / EASE IN-OUT / BOUNCE
5. **Iterations**: 1 (ONCE) / 2 (TWICE) / 3 (THRICE) / ∞ (INFINITE)
6. **Direction**: NORMAL / REVERSE / ALTERNATE / ALT-REV
7. **Intensity**: Subtle → Medium → Strong (0 to 1)

### Generated Prompt Example
```
Create a fade in animation for all elements on the page that transitions
from opacity 0 to 1 over 800ms with ease-in-out timing function and a 0ms delay
```

### Builder Tips
- Be specific about what elements should animate
- Combine animation types for more complex effects
- Consider context and purpose when selecting parameters
- Adjust settings to match desired attention level and impact

---

## Example Animation Prompts (Ready-to-Use)

### Hero Section Entrance
Tags: `fade in` `slide up` `staggered` `ease-out`
```
Create a staggered entrance animation for the hero section where the heading
fades in and slides up from 20px below, followed by the subheading 200ms later,
and finally the CTA button 300ms after that. Use an ease-out timing function
with a 600ms duration.
```

### Page Transition
Tags: `fade` `slide` `page transition`
```
Create a smooth page transition effect where the current page fades out while
sliding slightly to the left (transform: translateX(-20px)), and the new page
fades in while sliding from the right (transform: translateX(20px) to 0).
Use a 350ms duration with ease-in-out timing.
```

### Interactive Button Animation
Tags: `scale` `hover` `click` `multi-state`
```
Add a multi-state animation to call-to-action buttons where on hover, the button
scales to 1.03x with a subtle shadow increase (box-shadow: 0 4px 12px
rgba(0,0,0,0.1)), and on click, it scales down to 0.98x momentarily before
returning to hover state. Use a quick 150ms duration for click and 200ms for
hover with ease timing.
```

### Loading Animation
Tags: `loading` `scale` `fade` `infinite`
```
Create a loading animation using three dots that fade and scale in sequence.
Each dot should scale from 0.5 to 1.2 and back while fading from 0.2 to 1
opacity, with a 200ms delay between each dot. The animation should loop
infinitely to indicate ongoing loading.
```

### Card Hover Effects
Tags: `hover` `multi-property` `translate` `gradient`
```
Add hover animations to feature cards where the card subtly elevates
(transform: translateY(-5px)) with an increased shadow, while the icon within
the card scales up to 1.1x and changes color. The card background should also
have a subtle gradient shift effect. Implement with a 300ms transition using
ease-out timing.
```

### Scroll-Triggered Animations
Tags: `scroll` `slide` `fade` `directional`
```
Implement scroll-triggered animations for content sections where elements slide
in from different directions as they enter the viewport. Left side content should
slide in from left (-30px), right side content from right (30px), and center
content should fade in while moving up from 20px below. Use Intersection Observer
with a 0.1 threshold and 600ms animation duration.
```

### Customization Tips
- Use examples as templates, adapting values/timing/properties to your project
- Combine elements from different examples for complex animation systems
- Always consider performance impact and accessibility

