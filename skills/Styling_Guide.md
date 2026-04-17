# Aura.build — Styling Prompting Guide

Source: https://aura.build/learn/styling-prompting

---

## Overview

Creating effective prompts for styling UI components with different visual approaches, themes, colors, and effects.

### Styling Fundamentals

1. **Visual Hierarchy** — How elements are prioritized and organized to guide user attention.
   ```
   Create a card component with clear visual hierarchy: large title, medium subtitle,
   small body text, and a prominent call-to-action button using size, color, and
   spacing to establish importance.
   ```

2. **Style Type Selection** — Choose the overall visual approach matching brand and goals.
   ```
   Design a dashboard with glassmorphism style using backdrop blur, subtle transparency,
   and soft shadows to create depth while maintaining a modern, premium feel.
   ```

3. **Color Psychology** — Use colors strategically to influence emotions and behavior.
   ```
   Create a financial app interface using blue as the primary color to convey trust
   and stability, with green for positive values and red for negative values or warnings.
   ```

4. **Accessibility & Contrast** — Ensure designs work for all users with proper contrast.
   ```
   Design a form with WCAG AA compliant contrast ratios (4.5:1 minimum), clear focus
   states, and semantic color usage that doesn't rely solely on color to convey information.
   ```

### Common Styling Approaches

- **Modern Minimalism** — Clean lines, ample white space, purposeful color use.
- **Rich & Expressive** — Bold colors, gradients, dynamic visual elements.

---

## Style Types

| Style | Description |
|-------|-------------|
| **flat** | Clean, solid colors without shadows or gradients |
| **outline** | Transparent backgrounds with visible borders |
| **minimalist** | Simple, clean design with subtle elements |
| **glass** | Glassmorphism with backdrop blur effects |
| **ios** | iOS-style with rounded corners and depth |
| **material** | Material Design with elevation and shadows |

### Style Type Guidelines

- **Flat Design**: Perfect for modern, clean interfaces. Minimal distraction and fast loading.
- **Material Design**: Great for Android apps and Google-style interfaces. Clear hierarchy through elevation.
- **Glassmorphism**: Ideal for premium, modern applications. Depth while maintaining transparency.
- **Neumorphism**: Best for creative applications where you want a tactile, physical feel.

---

## Themes

| Theme | Description |
|-------|-------------|
| **light** | Bright backgrounds with dark text |
| **dark** | Dark backgrounds with light text |
| **auto** | Adapts to system preferences |

### Theme Considerations

#### Light Theme
- Better for reading and detailed work
- More familiar to most users
- Better for outdoor/bright environments
- Can appear more trustworthy and professional

#### Dark Theme
- Reduces eye strain in low-light conditions
- Saves battery on OLED screens
- Popular with developers and power users
- Can appear more modern and sophisticated

---

## Color Theory

### Color Psychology

| Color | Meaning | Use Case |
|-------|---------|----------|
| **Red** | Energy, urgency, passion | CTAs, warnings, important actions |
| **Blue** | Trust, stability, professionalism | Corporate and financial apps |
| **Green** | Growth, success, nature | Success states, eco-friendly brands |
| **Yellow** | Optimism, creativity, attention | Highlights and creative tools |
| **Purple** | Luxury, creativity, mystery | Premium and creative applications |
| **Gray** | Neutrality, sophistication, balance | Text and backgrounds |

### Color Harmony Rules

#### 60-30-10 Rule
Use 60% dominant color, 30% secondary color, and 10% accent color for balanced designs.

#### Complementary Colors
Colors opposite on the color wheel create high contrast. Use sparingly for maximum impact.

#### Analogous Colors
Colors next to each other on the wheel create harmony. Perfect for gradients and subtle variations.

---

## Colors

### Primary Colors

| Color | Hex |
|-------|-----|
| Blue | `#3B82F6` |
| Red | `#EF4444` |
| Green | `#10B981` |
| Yellow | `#F59E0B` |
| Purple | `#8B5CF6` |
| Pink | `#EC4899` |
| Indigo | `#6366F1` |
| Gray | `#6B7280` |
| Orange | `#F97316` |
| Teal | `#14B8A6` |
| Cyan | `#06B6D4` |
| Emerald | `#059669` |

### Extended Palette

| Color | Hex |
|-------|-----|
| Lime | `#65A30D` |
| Amber | `#D97706` |
| Rose | `#F43F5E` |
| Violet | `#7C3AED` |
| Fuchsia | `#D946EF` |
| Sky | `#0EA5E9` |
| Slate | `#64748B` |
| Zinc | `#71717A` |
| Neutral | `#737373` |
| Stone | `#78716C` |

### Color Usage Guidelines

- **Primary Color**: Main actions, links, brand elements (5-10% of interface)
- **Secondary Color**: Secondary actions, supporting elements (15-20% of interface)
- **Neutral Colors**: Text, backgrounds, borders (70-80% of interface)
- **Semantic Colors**: Red for errors, green for success, yellow for warnings

---

## Shadows & Depth

| Level | Description |
|-------|-------------|
| **None** | No shadow effects |
| **Small** | Subtle shadow for minimal depth |
| **Medium** | Standard shadow for good depth |
| **Large** | Prominent shadow for strong depth |
| **Extra Large** | Dramatic shadow for maximum impact |
| **2xl** | Very dramatic shadow for hero elements |
| **Inner** | Inset shadow for pressed/recessed effect |

### Elevation Hierarchy

- **Level 1**: Cards, panels
- **Level 2**: Buttons, inputs
- **Level 3**: Dropdowns, tooltips
- **Level 4**: Modals, overlays

### Shadow Best Practices

- Use consistent shadow directions (usually bottom-right)
- Increase shadow intensity for higher elevation
- Consider light source and environment
- Use colored shadows sparingly for special effects
- Test shadows in both light and dark themes

---

## Responsive Design

### Breakpoints

| Device | Width | Layout |
|--------|-------|--------|
| **Mobile** | 0-767px | Single column |
| **Tablet** | 768-1023px | Flexible |
| **Desktop** | 1024px+ | Multi-column |

### Mobile Considerations
- Touch targets at least 44px
- Larger text sizes for readability
- Simplify navigation and reduce clutter
- Thumb-friendly placement
- Single-column layouts

### Desktop Enhancements
- Detailed hover states and animations
- Multi-column layouts
- Keyboard navigation support
- Contextual tooltips and help
- Mouse and trackpad optimization

### Breakpoint Strategy
- **Mobile (0-640px)**: Single column, large touch targets, simplified navigation
- **Tablet (641-1024px)**: Two-column layouts, medium touch targets, adaptive navigation
- **Desktop (1025px+)**: Multi-column layouts, hover states, detailed interactions

---

## Accessibility

### Contrast Requirements

| Level | Ratio | Applies To |
|-------|-------|------------|
| WCAG AA | 4.5:1 minimum | Normal text |
| WCAG AA | 3:1 minimum | Large text |
| WCAG AAA | 7:1 minimum | Normal text (enhanced) |

### Accessibility Checklist

#### Color & Contrast
- Maintain 4.5:1 contrast ratio for normal text
- Maintain 3:1 contrast ratio for large text
- Don't rely solely on color to convey information
- Test with color blindness simulators

#### Interactive Elements
- Provide clear focus indicators
- Ensure touch targets are at least 44px
- Use semantic HTML elements
- Provide alternative text for images

---

## Advanced Styling Techniques

### Gradient Techniques

#### Linear Gradients
- Blue to Purple
- Green to Blue
- Pink to Red

#### Radial Gradients
- Radial Sunset
- Radial Ocean
- Radial Galaxy

### CSS Custom Properties (Variables)

```css
:root {
  --primary-color: #3B82F6;
  --secondary-color: #6B7280;
  --background-color: #FFFFFF;
  --text-color: #1F2937;
  --border-radius: 8px;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
}

[data-theme="dark"] {
  --background-color: #111827;
  --text-color: #F9FAFB;
  --secondary-color: #9CA3AF;
}
```

### Animation & Transitions
- Micro-interactions (hover states)
- Loading states
- State changes

---

## Color Palettes

| Palette | Description |
|---------|-------------|
| **modern** | Clean, professional palette for modern applications |
| **vibrant** | Energetic colors for creative and youthful brands |
| **earth** | Natural, warm tones inspired by earth elements |
| **monochrome** | Sophisticated grayscale palette for elegant designs |
| **ocean** | Cool blues and teals reminiscent of ocean depths |
| **sunset** | Warm gradient colors inspired by sunset skies |

---

## Interactive Prompt Builder Parameters

### Inputs
1. **Style Type**: flat / outline / minimalist / glass / ios / material
2. **Theme**: light / dark / auto
3. **Primary Color**: Any from the color palette
4. **Shadow Depth**: none / small / medium / large / xl / 2xl
5. **Device Optimization**: desktop / tablet / mobile
6. **Color Palette**: modern / vibrant / earth / monochrome / ocean / sunset

---

## Best Practices

### ✅ Do's
- Maintain consistency across all components and pages
- Consider accessibility and color contrast in all design decisions
- Test designs in both light and dark themes
- Use shadows purposefully to create clear visual hierarchy
- Choose colors that align with brand identity and target audience
- Implement responsive design principles from the start
- Use semantic color meanings (red for errors, green for success)
- Create a design system with reusable components
- Test with real users and gather feedback
- Consider cultural color associations for global audiences

### ❌ Don'ts
- Don't use too many colors in one design (stick to 3-5 main)
- Avoid low contrast combinations that hurt readability
- Don't overuse shadows or visual effects
- Avoid mixing incompatible style types within the same interface
- Don't ignore mobile and responsive considerations
- Don't use color as the only way to convey information
- Don't follow trends blindly without considering users
- Don't neglect performance implications of complex styling
- Don't make assumptions about user preferences

### 💡 Pro Tips
- Use 60-30-10 rule for color distribution
- Create hover/focus states 10-20% darker/lighter than base
- Implement consistent border radius system (4px, 8px, 16px)
- Use CSS custom properties for easy theme switching
- Use color palette generator for harmonious combinations
- Test with color blindness simulators
- Use relative units (rem, em) for scalability
- Implement consistent spacing scale (4px, 8px, 16px, 32px)
- Consider emotional impact of color choices
- Document design decisions for team consistency

---

## Example Prompts (Ready-to-Use)

### Modern SaaS Dashboard
```
Create a modern SaaS dashboard with glassmorphism design using an adaptive theme
that responds to system preferences. Use blue (#3B82F6) as the primary accent color
with subtle large shadows for depth. The background should be white in light mode
and dark gray (#111827) in dark mode, with light gray borders (#E5E7EB) that adapt
to neutral borders (#374151) in dark mode. Design should be optimized for desktop
screens with larger elements and detailed hover states. Use the modern color palette
for consistency with supporting colors of gray-100, gray-800, and blue-600. Ensure
the design is professional, accessible with WCAG AA compliance, and follows current
UI/UX best practices with proper contrast ratios and responsive behavior. Include
subtle micro-interactions and smooth transitions between states.
```

### Mobile-First E-commerce App
```
Design a mobile-first e-commerce app interface with iOS-style design using rounded
corners and medium shadows. Use a light theme with green (#10B981) as the primary
accent color for trust and growth associations. Apply medium shadows for depth and
hierarchy. The background should be white with gray borders for clean separation.
Design should be optimized for mobile devices with large touch targets (44px minimum),
single-column layouts, and thumb-friendly navigation. Use the earth color palette
for warmth with supporting colors including amber-600, orange-500, and green-700.
Ensure the design feels native to iOS users with proper spacing, readable typography,
and accessible color contrast ratios above 4.5:1. Include loading states, error
handling, and success feedback with appropriate semantic colors.
```

### Creative Portfolio Website
```
Create a creative portfolio website with brutalist design using bold, raw, and
geometric elements. Use a dark theme with purple (#8B5CF6) as the primary accent
color to convey creativity and luxury. Apply dramatic extra-large shadows for maximum
visual impact and artistic flair. The background should be black with high-contrast
white borders for bold separation. Design should be optimized for desktop screens
with artistic layouts and experimental navigation patterns. Use the vibrant color
palette for creative energy with supporting colors including purple-500, pink-400,
yellow-400, and green-400. Ensure the design is memorable and artistic while
maintaining basic accessibility standards. Include bold typography, asymmetrical
layouts, and striking visual elements that showcase creative work effectively.
```

### Minimalist Blog Platform
```
Design a minimalist blog platform with flat design using clean, solid colors and no
shadows for maximum readability. Use a light theme with gray (#6B7280) as the primary
accent color for sophisticated neutrality. Apply no shadows to maintain the clean,
distraction-free aesthetic. The background should be white with subtle gray borders
for gentle content separation. Design should be optimized for all devices with
responsive typography and flexible layouts. Use the monochrome color palette for
elegant simplicity with supporting colors of gray-900, gray-700, gray-500, and
gray-300. Ensure the design prioritizes content readability with excellent typography
hierarchy, generous white space, and WCAG AAA contrast compliance. Focus on clean
lines, ample spacing, and distraction-free reading experience with subtle
interactive elements.
```

### Financial Technology App
```
Create a financial technology app with Material Design using elevation and depth
principles. Use an adaptive theme with blue (#3B82F6) as the primary accent color
to convey trust and stability. Apply medium shadows for clear hierarchy and
professional appearance. The background should adapt between white and dark gray
based on user preference, with borders that maintain proper contrast in both themes.
Design should be optimized for tablet devices with medium-sized touch targets and
flexible grid layouts. Use the ocean color palette for trustworthiness with supporting
colors including blue-900, blue-700, cyan-500, and teal-400. Ensure the design meets
financial industry standards for accessibility and security perception. Include clear
data visualization, secure interaction patterns, and professional micro-interactions
that build user confidence.
```

### Gaming Community Platform
```
Design a gaming community platform with neumorphic design using soft, extruded
plastic-like appearance for a tactile, engaging feel. Use a dark theme with orange
(#F97316) as the primary accent color for energy and excitement. Apply subtle small
shadows with inner shadows for pressed effects on interactive elements. The background
should be dark gray with matching borders for seamless integration. Design should be
optimized for desktop screens with gaming-focused layouts and immersive navigation.
Use the sunset color palette for dynamic energy with supporting colors including
orange-500, red-500, pink-500, purple-500, and yellow-400. Ensure the design appeals
to gaming audiences with high contrast for visibility during gameplay, customizable
themes, and engaging visual feedback. Include animated elements, achievement displays,
and community features that enhance the gaming experience.
```

---

## Resources & Tools

### Color Tools & Generators
- **Coolors** — Color palette generator
- **Color Hunt** — Curated color palettes
- **Paletton** — Color scheme designer

### Accessibility & Contrast Tools
- **WebAIM Contrast Checker** — WCAG compliance testing
- **Color Blindness Simulator** — Test color accessibility
- **Accessible Colors** — Find accessible color combinations
- **axe DevTools** — Chrome extension for accessibility testing
- **Stark (Figma Plugin)** — Design accessibility toolkit
- **WAVE Web Accessibility Evaluator** — Web page accessibility analysis

### Design Systems & References
- **Material Design** — Google's design system
- **Apple HIG** — iOS design guidelines
- **Tailwind CSS** — Utility-first CSS framework

### Typography & Spacing Tools
- **Type Scale** — Typography scale generator
- **Gridlover** — Typography rhythm tool
- **Spacing.js** — Spacing system calculator


