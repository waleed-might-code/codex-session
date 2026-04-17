# Aura.build — Documentation & Prompting Guide

Source: https://aura.build (public docs pages)

## What is Aura?

Aura is an AI-powered HTML/CSS design generation tool. Users write natural language prompts and get production-ready HTML output. It focuses on:
- HTML generation from prompts
- Template marketplace (users can sell templates)
- Component library
- Custom domain support
- Device framing (iPhone, iPad, Desktop browser mockups)

**Key differentiator:** Aura is design/UI-first — it generates complete HTML/CSS visuals, not full-stack apps. It positions itself between a design tool (Figma) and a code generator (v0/Lovable).

**Made with Cursor** (stated in footer).

---

## Product Structure

- **Create** — AI-powered design generation
- **Templates** — Pre-made templates (marketplace)
- **Components** — Reusable UI components
- **Assets** — Design assets
- **Skills** — User skill system
- **Learn** — Tutorials & documentation
- **Pricing** — Subscription tiers
- **Changelog** — Updates

---

## HTML Generation Tips

### 1. Specify the Framework or Library
Mention whether you want vanilla HTML/CSS or a specific framework like Tailwind CSS, Bootstrap, or Material UI.

### 2. Define the Component Structure
Outline the key elements you need.

### 3. Include Responsive Behavior Requirements
Specify how your design should adapt to different screen sizes.

### 4. Reference a Style Guide or Brand Colors
Provide color codes or style information.

### 5. Mention Interactive Elements
Describe any animations or effects.

### 6. Provide a Reference or Inspiration
Point to existing designs.

---

## Component Prompt Templates

### Hero Section
Standard hero section prompt template.

### Pricing Table
Pricing comparison layout.

### Navigation Bar
Top navigation with responsive behavior.

### Testimonial Cards
Customer testimonial card layout.

---

## Responsive Design Strategies

### 1. Specify Breakpoints
Define exactly when layouts should change.

### 2. Describe Mobile-Specific Behaviors
Detail how elements should adapt.

### 3. Prioritize Content for Mobile
Explain what content is most important.

### 4. Specify Touch-Friendly Elements
Request appropriate sizing for touch interfaces.

---

## Device Framing

Aura supports framing designs within device mockups:

### Desktop Browser Frame
Frame design in a browser window with traffic lights (close, minimize, maximize buttons).

### iPhone Frame
Showcase mobile designs within an iPhone frame with notch and buttons.

### iPad Frame
Present tablet designs in an iPad frame with characteristic bezels.

### Framing Tips
1. **Specify exact device models** — "Frame this design in an iPhone 14 Pro" is better than "put this in a phone frame."
2. **Request contextual elements** — Include URL bars for browser frames or status bars with realistic time/battery indicators.
3. **Add environmental context** — "Show the iPhone on a wooden desk with soft lighting" creates more realistic mockups.
4. **Consider angle and perspective** — "Show the iPad at a slight angle (15°) with a subtle shadow beneath it" adds depth.

---

## Styling & Frameworks

### Framework Selection
Be explicit about CSS frameworks — "Generate a contact form using Bootstrap 5 with form validation and floating labels."

### Class Patterns
Include specific class patterns — For Tailwind: "Use Tailwind's container class with mx-auto and px-4."

### Component Libraries
Specify design system — "Create a dashboard layout using Material UI components."

### CSS Architecture
Mention CSS architecture — "Use BEM methodology for CSS class naming."

### Reference Known Styles
Reference favorite apps — "Design a settings page in the style of Apple's iOS interface" or "Create a music player with Spotify's dark theme aesthetic."

---

## Typography & Fonts

### Supported Modern Web Fonts

#### Sans-Serif UI Fonts
| Font | Description | Weights |
|------|-------------|---------|
| **Inter** (Popular) | Versatile, highly legible sans-serif designed for screens | 300-700 |
| **Geist** (Trending) | Modern sans-serif by Vercel with compact spacing | 300-700 |
| **Plus Jakarta Sans** | Friendly sans-serif for digital interfaces | 300-800 |
| **Manrope** | Modern geometric sans-serif with clean lines | 300-800 |
| **IBM Plex Sans** | Corporate typeface with excellent legibility | 300-700 |

#### Monospace
| Font | Description | Weights |
|------|-------------|---------|
| **Geist Mono** | Clean monospaced companion to Geist Sans | 300-700 |

### Typography Scale
| Level | Size |
|-------|------|
| H1 Display | 2.5rem - 3rem (40-48px) |
| H2 Heading | 1.75rem - 2rem (28-32px) |
| H3 Subheading | 1.25rem - 1.5rem (20-24px) |
| Body Text | 1rem (16px) |
| Small Text | 0.875rem (14px) |
| Micro / Caption | 0.75rem (12px) |

### Font Weights
| Weight | Usage |
|--------|-------|
| Light (300) | Subtitles, secondary text |
| Regular (400) | Body text, paragraphs |
| Medium (500) | Emphasis, subheadings |
| Semibold (600) | Buttons, important text |
| Bold (700) | Headings, strong emphasis |

### Letter Spacing
| Type | Value |
|------|-------|
| Tight | -0.025em (for large headlines) |
| Normal | 0em (for body text) |
| Wide | 0.025em (for improved legibility) |
| Extra Wide | 0.1em (for uppercase text) |

### Typography Prompt Builder Parameters
1. **Typeface Family** — Sans-Serif / Serif / Monospace
2. **Font Size Scale** — Headings (40-60px), Subheadings (28-36px), Body (14-16px)
3. **Font Weight Distribution** — Headings (~640), Subheadings (~560), Body (~460)
4. **Letter Spacing** — Headings (-0.06em), Body (0.00em), ALL CAPS (0.05em)

---

## Animation Techniques

### Fade-in Effects
Gradually reveal elements for a subtle, elegant entrance.

### Slide-in Animations
Move elements into position from off-screen.

### Blur Effects
Transition from blurred to clear for a dramatic reveal.

### Sequenced Animations
Stagger animations across multiple elements.

### Animation Timing & Delays
1. **Duration** — Set animation-duration for cycle length.
2. **Delay** — Use animation-delay to postpone start.
3. **Timing Function** — Control acceleration with animation-timing-function.
4. **Negative Delays** — Use negative values to start partway through cycle.

### Best Practices
- Keep animations subtle and purposeful
- Use `prefers-reduced-motion` media query
- Aim for animations under 500ms for UI interactions

---

## JavaScript Visualization Libraries (Supported)

| Library | Purpose |
|---------|---------|
| **Three.js** | 3D scenes, models, and animations in browser |
| **COBE.js** | Interactive 3D globes |
| **Vanta.js** | Animated backgrounds with minimal config |
| **GSAP** | Professional-grade animation library |

---

## Tailwind Design System Reference

### Color System
Numeric scale from 50 (lightest) to 900 (darkest).

### Spacing System
1 unit = 0.25rem (4px default).

### Typography Scale
text-xs to text-9xl with standardized line heights.

### Responsive Breakpoints
Prefixes: sm, md, lg, xl, 2xl.

---

## Layout Examples

Aura supports generating these common patterns:
- **Bento Grid** — Modern grid layouts
- **Modal Dialog** — Overlay dialogs
- **List Layout** — Structured list views
- **Alerts** — Notification/alert components
- **Sidebar Navigation** — Side panel navigation
- **Advanced Grid Layout** — Complex grid systems
- **Action Bar / Toolbar** — Button/action toolbars
- **Top Navigation Bar** — Header navigation

---

## Advanced Prompting Techniques

### Chain Your Requests
Start with basic structure, then refine: "Now add form validation to the contact form with appropriate error messages."

### Provide Example Code Snippets
Share code you like: "Create a product listing page following this component structure but styled with Tailwind CSS."

### Use Persona-Based Prompting
"Create HTML/CSS for a pricing section as if you were an experienced UI designer specializing in SaaS products."

### Request Accessibility Features
"Create a form with WCAG 2.1 AA compliance, including proper aria labels, keyboard navigation, and focus states."

---

## Key Observations for Moodular Comparison

1. **Output format**: Aura generates pure HTML/CSS — no React, no backend, no full-stack
2. **No tools/function calling visible**: Aura appears to use direct prompting without exposed tool schemas
3. **Heavy design system guidance**: Typography builder, animation guides, device framing are first-class features
4. **Tailwind-first**: Strong Tailwind CSS integration as the default styling system
5. **Marketplace model**: Users can sell generated templates — monetization angle
6. **Model support**: Mentions GPT 5.1 and Gemini 3 in tutorials — multi-model
7. **Focus**: Pure frontend/visual design, not application logic or backend
8. **Built with Cursor**: Noted in footer


