# Aura.build — Typography Prompting Guide

Source: https://aura.build/learn/typography-prompting

---

## Introduction to Typography Prompting

Typography plays a crucial role in design, influencing readability, hierarchy, and overall aesthetic. Properly crafted typography prompts help AI tools generate designs with a professional typographic foundation.

### Elements of Good Typography

1. **Hierarchy** — Clear visual distinction between headings, subheadings, and body text that guides the reader's eye.
2. **Readability** — Appropriate font choices, sizes, and spacing that make content easy to read across different devices.
3. **Consistency** — A systematic approach to type that creates harmony throughout the design.

---

## Font Fundamentals

### Sans-Serif Fonts
Clean, modern fonts without decorative strokes. Ideal for interfaces, headings, and body text in digital designs.

| Font | Sample |
|------|--------|
| **Inter** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |
| **Geist** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |

### Serif Fonts
Classic fonts with small decorative strokes. Used for body text in print and for traditional, sophisticated looks.

| Font | Sample |
|------|--------|
| **Merriweather** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |
| **IBM Plex Serif** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |

### Display Fonts
Decorative fonts designed for large headings and titles. Not suitable for body text. Use sparingly.

| Font | Sample |
|------|--------|
| **Playfair Display** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |

### Monospace Fonts
Each character takes up the same horizontal space. Ideal for code snippets and technical content.

| Font | Sample |
|------|--------|
| **Geist Mono** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |

### Condensed Fonts
Narrower versions of standard typefaces. Ideal for space-constrained layouts and data-dense interfaces.

| Font | Sample |
|------|--------|
| **IBM Plex Condensed** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |

### Expanded Fonts
Wider versions of standard typefaces. Great for creating impact in headlines.

| Font | Sample |
|------|--------|
| **Encode Sans Expanded** | AaBbCcDdEeFfGgHhIiJjKkLl 0123456789 |

### Typography Terminology

| Term | Description |
|------|-------------|
| **Font Weight** | Thickness of characters, 100 (thin) to 900 (black) |
| **Font Size** | Size in px, pt, or rem |
| **Line Height** | Space between lines of text |
| **Letter Spacing** | Space between characters |

---

## Typography Pairing

### Font Pairing Principles
The most effective font combinations create visual contrast while sharing some subtle quality that connects them. Typically, pair a distinctive headline font with a more neutral body font.

### Classic Font Pairings

#### Serif + Sans-Serif
**Playfair Display + Inter**
Classic contrast — elegance of serif display with clean readability of modern sans-serif.
```
Create a landing page using Playfair Display for headings and Inter for body text.
Use a dramatic size contrast with headings at 64px and body text at 16px.
```

#### Sans-Serif + Sans-Serif
**Bricolage Grotesque + Inter**
Modern, cohesive look using contrast in weights rather than font types.
```
Design a website with Bricolage Grotesque (600 weight) for headings and
Inter for body text. This creates a strong but cohesive visual hierarchy.
```

#### Serif + Serif
**Merriweather + IBM Plex Serif**
Sophisticated, editorial look perfect for longform content.
```
Generate a blog layout using Merriweather Bold for headings and IBM Plex Serif
for body text, creating a scholarly, refined typography system.
```

### Pairing Strategies

1. **Contrast in Classification** — Pair fonts from different categories (serif + sans-serif, display + sans-serif).
2. **Contrast in Weight** — Same family, dramatic weight differences (Inter Black 900 for headings, Inter Regular 400 for body).
3. **Contrast in Size** — Significant size differences (headings 3rem/48px, body 1rem/16px).
4. **Historical/Stylistic Connections** — Fonts sharing a design era (Futura + Gill Sans for mid-century modern).

---

## Full Font Showcase

### Sans-Serif Fonts

| Font | Style | Weights | Description |
|------|-------|---------|-------------|
| **Inter** | Popular | 300-700 | Versatile, highly legible sans-serif designed for screens |
| **Bricolage Grotesque** | Trending | 300-700 | Contemporary grotesque with quirky details and excellent readability |
| **Geist Sans** | — | 300-700 | Modern sans-serif by Vercel with compact spacing and softly bent arcs |
| **Plus Jakarta Sans** | — | 300-700 | Friendly sans-serif designed for digital interfaces |

### Serif Fonts

| Font | Weights | Description |
|------|---------|-------------|
| **Merriweather** | 300, 400, 700, 900 | Traditional serif with excellent readability for longform content |
| **IBM Plex Serif** | 300-700 | Contemporary serif with excellent legibility, technical and precise |
| **Playfair Display** | 400-900 | Elegant display serif with dramatic thick-thin transitions, ideal for headlines |

### Monospace Fonts

| Font | Weights | Description |
|------|---------|-------------|
| **Geist Mono** | 300-700 | Clean monospaced companion to Geist Sans, ideal for code blocks |
| **IBM Plex Mono** | 300-700 | Technical-looking monospace, excellent for code and technical docs |

### How to Reference Fonts in Prompts

1. **Be specific about font names** — "Use Playfair Display" not "use an elegant serif"
2. **Specify weights and styles** — Include weight numbers (400, 700) or names (Regular, Bold)
3. **Include fallback options** — "Use Inter or a similar modern sans-serif"
4. **Reference font sources** — Mention "Google Fonts" to clarify availability

---

## Typography Prompt Builder

### Parameters

#### 1. Typeface Family Categories
- SANS SERIF
- SERIF
- MONOSPACE
- DISPLAY
- GROTESQUE

#### 2. Font Size Scale Options

| Element | Small | Medium | Large |
|---------|-------|--------|-------|
| Heading | 20-32px | 32-40px | 48-64px |
| Subheading | 16-20px | 20-28px | 32-40px |
| Body Text | 12-14px | 14-16px | 16-18px |

#### 3. Font Weight Options

| Element | Options |
|---------|---------|
| Heading | 400, 500, 600, 700 |
| Subheading | 300, 400, 500, 600 |
| Body Text | 300, 400, 500, 600 |

#### 4. Letter Spacing Options

| Element | Options |
|---------|---------|
| Heading | -0.05em, -0.02em, 0em, 0.02em |
| Body Text | -0.02em, 0em, 0.01em, 0.02em |
| ALL CAPS | 0.02em, 0.05em, 0.1em, 0.15em |

### Generated Prompt Example
```
Create a landing page using Inter font with the following typography scale:

• Headings: 60-80px, font-weight: 600, letter-spacing: -0.02em
• Subheadings: 20-28px, font-weight: 500, letter-spacing: 0.00em
• Body text: 16-20px, font-weight: 400, line-height: 1.5
• Button text: 16px, font-weight: 500
• Ensure proper contrast and hierarchy between text elements
```

---

## Typography Examples (Ready-to-Use Prompts)

### Modern Business Website
**Fonts:** Inter Bold (headings), Inter Regular (body), Inter SemiBold (buttons)

```
Create a business homepage using Inter with the following typography scale:
• Headings: 48px, font-weight: 700, letter-spacing: -0.02em
• Subheadings: 24px, font-weight: 600, letter-spacing: -0.01em
• Body text: 16px, font-weight: 400, line-height: 1.5
• Button text: 16px, font-weight: 600
• Caption text: 12px, font-weight: 400, letter-spacing: 0.02em
• Use a dark gray (#333) for text on white backgrounds for readability
```

### Editorial Blog
**Fonts:** Playfair Display (headings), Merriweather (body)

```
Design a blog layout with elegant typography:
• Article titles: Playfair Display, 56px, font-weight: 700, line-height: 1.1
• Section headings: Playfair Display, 32px, font-weight: 600, line-height: 1.2
• Body text: Merriweather, 18px, font-weight: 400, line-height: 1.6
• Pull quotes: Playfair Display italic, 24px, line-height: 1.4
• Category labels: Merriweather Bold, 12px, ALL CAPS, letter-spacing: 0.05em
• Use a max-width of 680px for text containers to improve readability
```

### Tech Startup / SaaS
**Fonts:** Bricolage Grotesque (headings), Inter (UI text)

```
Create a SaaS landing page with modern typography:
• Hero heading: Bricolage Grotesque, 64px, font-weight: 700, letter-spacing: -0.03em
• Feature titles: Bricolage Grotesque, 28px, font-weight: 600, letter-spacing: -0.01em
• UI text: Inter, 16px, font-weight: 400, line-height: 1.5
• Button text: Inter, 14px, font-weight: 600, letter-spacing: 0.01em
• Nav links: Inter, 14px, font-weight: 500
• Use vibrant blue (#3B82F6) for interactive elements with white text
```

### E-commerce Store
**Fonts:** Plus Jakarta Sans (all)

```
Design an e-commerce store with clean, accessible typography:
• Page titles: Plus Jakarta Sans, 40px, font-weight: 800
• Product names: Plus Jakarta Sans, 24px, font-weight: 700, line-height: 1.2
• Product descriptions: Plus Jakarta Sans, 16px, font-weight: 400, line-height: 1.5
• Prices: Plus Jakarta Sans, 18px, font-weight: 700
• Button text: Plus Jakarta Sans, 14px, font-weight: 600
• Category labels: Plus Jakarta Sans, 12px, font-weight: 600, letter-spacing: 0.02em
• Ensure strong color contrast for prices and CTAs for better accessibility
```

---

## Responsive Typography

### Why Responsive Typography Matters
Typography that works on desktop might be unreadable on mobile. Responsive typography ensures optimal readability across all screen sizes.

### Strategy 1: Fluid Typography
Font sizes scale smoothly between minimum and maximum based on screen width.

```
Create a landing page with fluid typography that scales between mobile and desktop:
• Headings: clamp(32px, 5vw, 64px)
• Subheadings: clamp(24px, 3vw, 36px)
• Body text: clamp(16px, 1vw, 18px)
```

### Strategy 2: Breakpoint-Based Typography
Font sizes change at specific screen width breakpoints.

```
Create a landing page with breakpoint-based typography:
• Headings: 48px on desktop, 36px on tablet, 24px on mobile
• Subheadings: 36px on desktop, 28px on tablet, 18px on mobile
• Body text: 18px on desktop, 16px on tablet, 14px on mobile
• Button text: 16px on desktop, 14px on tablet, 12px on mobile
```

---

## Text Animation Techniques

### Character Reveal
Reveal text character by character, creating a typing effect.
```
Create a typing animation that reveals each character with a 50ms delay
between characters for the main headline using Inter.
```

### Word Fade Up
Animate words fading in and moving upward with staggered timing.
```
Create a staggered fade-up animation for each word in the tagline,
with 100ms delay between words, using Inter font.
```

### Letter by Letter
Each letter appears with a scaling effect, creating dynamic and playful animation.
```
Create a letter-by-letter animation that reveals each character with a subtle
scale effect and 80ms staggered delay, using a bold display font.
```

### Combined Animation
Combines fade, slide, and blur effects letter by letter for sophisticated entrance.
```
Create a complex animation that fades in, slides up, and reduces blur for each
letter with a 60ms staggered delay between characters using Inter at 60-80px.
```

### Gradient Text
Apply animated gradient backgrounds to text.
```
Apply a moving gradient background from blue to purple to the main heading,
with the gradient animating horizontally over 3 seconds in a loop.
```

### Clipped Reveal
Text reveals through a clipping mask while sliding into position.
```
Create a text animation that slides in with a clipping mask effect that reveals
the title text from left to right over 800ms with an ease-out timing function.
```

### Animation Best Practices
- Keep text animations subtle and brief
- Ensure animated text remains readable throughout
- For headings, choose animations that complement the font's character
- Elegant transitions for serif fonts, clean animations for sans-serif
- Consider using animation to emphasize font weight changes
- Implement `prefers-reduced-motion` for accessibility

---

## Pro Tips

1. Include both specific font names AND fallback categories
2. Specify exact weights rather than just "bold"
3. Include letter-spacing for headings and ALL CAPS text
4. For body text, always specify line-height for readability
5. For best results, customize prompt templates with your specific design requirements


