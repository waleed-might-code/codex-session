# Aura.build — Layout Prompting Guide

Source: https://aura.build/learn/layout-prompting

---

## Responsive Design

### Responsive Design Fundamentals

1. **Mobile-first approach** — Always design for mobile first, then expand to larger screens.
   ```
   Create a mobile-first layout that starts as a single column on phones (under 640px)
   and expands to a two-column grid on tablets and desktops.
   ```

2. **Specify breakpoints** — Define exactly when layouts should change based on common device sizes.
   ```
   Create a hero section with text and image that switches from stacked (mobile)
   to side-by-side at 768px, with appropriate spacing adjustments at each breakpoint.
   ```

3. **Content priority** — Specify which content is most important on smaller screens.
   ```
   Design a product page where the purchase button is more prominent on mobile,
   appearing right after the product title and before the detailed description.
   ```

4. **Navigation transformation** — Describe how navigation should transform across devices.
   ```
   Create a navigation system that's a full-width horizontal menu on desktop (1024px+),
   a condensed horizontal menu on tablet (768px-1023px), and a hamburger menu with
   slide-out drawer on mobile (below 768px).
   ```

### Important Note
Don't just say "make it responsive" — specify exactly how the layout should change at different screen sizes.

### Common Responsive Patterns

#### Column Drop
Multi-column layout stacks vertically as screen width decreases.
```
Create a three-column layout that becomes a single column on mobile,
stacking the sections in order of importance.
```

#### Layout Shifter
Elements reposition, not just stack, as screen size changes.
```
Design a product showcase where the gallery is on the left on desktop,
but moves above the product information on mobile for better visual flow.
```

#### Off Canvas
Secondary content is placed off-screen and shown when needed.
```
Create a mobile layout with a hamburger menu that reveals a slide-out
navigation drawer from the left side when clicked.
```

#### Mostly Fluid
Grid-based layout that reflows and eventually stacks on smaller screens.
```
Create a fluid grid layout with 4 items per row on large screens,
2 per row on tablets, and 1 per row on mobile.
```

---

## List Layouts

List layouts are among the most common and versatile UI patterns — excellent for displaying collections of similar items in a clean, scannable format.

### Basic List Layout
```
Create a list of user profiles with circular avatar images on the left,
name and role information in the middle, and a chevron icon button on
the right for navigation.
```

### Contact/User Lists
```
Create a contacts list with user avatars, names, job titles, and action
buttons (call, message) aligned to the right. Use subtle hover effects
for interactivity.
```

### Settings Lists
```
Design a settings menu with left-aligned icons, setting names, and toggle
switches on the right. Include clear section dividers and subtle background
indicators for the active setting.
```

### Notification Lists
```
Create a notification feed with color-coded categories (red for alerts,
blue for information, green for success), notification content, and
relative timestamps. Include an unread indicator and dismiss button.
```

### Product Lists
```
Design a product list for an e-commerce app with product images, names,
prices, brief descriptions, and add-to-cart buttons. Include stock
indicators and rating stars.
```

### List Layout Best Practices
- Maintain consistent spacing between list items
- Use clear visual hierarchies to distinguish primary and secondary information
- Consider adding dividers or alternating background colors for long lists
- Ensure touch targets are at least 44px tall on mobile
- Include clear feedback states (active, hover, focus)

---

## Grid Layouts

Grid layouts organize content in a structured, modular format that creates visual harmony.

### Advanced Grid Layout
```
Create a responsive grid dashboard layout with various card sizes. The main
metrics card should span 3 columns and 2 rows, with smaller cards for
secondary metrics. Use grid-template-areas for complex content organization.
```

### Card Grids
```
Design a product grid with 4 cards per row on desktop, 2 per row on tablets,
and 1 per row on mobile. Each card should have a product image, name, price,
and an add-to-cart button that appears on hover.
```

### Masonry Grid
```
Create a masonry-style image gallery where images maintain their aspect ratios
but align to a grid. Include lazy loading for images and a lightbox effect
when clicked.
```

### Feature Grid
```
Design a features grid with 3 columns on desktop and 1 column on mobile.
Each feature should have an icon at the top, a heading, and a brief
description. Use a consistent icon style and color scheme.
```

### Dashboard Grid
```
Create a metrics dashboard with a mix of card sizes: small cards for key
metrics in the top row (spanning 1 column each) and larger charts below
(spanning 2-3 columns). Include card headers with titles and optional
dropdown menus.
```

### Grid Layout Prompt Specifications
When requesting grid layouts, specify:
- Number of columns at different breakpoints (e.g., 4 on desktop, 2 on tablet)
- Gap sizes between grid items (e.g., 16px horizontally, 24px vertically)
- Whether items should have equal heights or maintain aspect ratios
- Any specific items that should span multiple columns or rows
- Minimum/maximum sizes for grid items (important for responsive designs)

---

## Bento Layouts

Bento layouts (named after Japanese lunch boxes) feature a grid of content blocks with varying sizes and proportions. Effective for dashboards, portfolios, and content-rich home pages.

### Bento Grid
```
Design a bento grid layout for a portfolio homepage with a featured project
(2x2 grid space) on the left, and two smaller project cards (1x1 each)
stacked on the right. Each card should include a project image, title, and
brief description.
```

### Dashboard Bento
```
Create a metrics dashboard with a bento layout: small KPI cards in the top
row (1x1 each), a large chart in the middle (2x2), bar charts on the bottom
left (2x1), and a scrollable activity feed on the bottom right (2x1).
```

### Content Showcase Bento
```
Design a content showcase with a featured article (2x2) with cover image
and overlay text, a sidebar (1x3) with newsletter signup, and two smaller
article cards (1x1 each) below the main feature.
```

### Product Features Bento
```
Create a product features showcase with a banner section across the top
(4x1) that includes a headline, brief description, and illustration. Below,
add four feature cards (1x1 each) with icons, titles, and short descriptions.
```

### Media Gallery Bento
```
Design a media gallery with a main large image (3x2), a wide image on the
top right (3x1), and two smaller images below (2x1 and 1x1). Include hover
effects that display image titles and photographers.
```

### Bento Layout Design Principles
- Create clear visual hierarchy with larger cells for more important content
- Maintain spacing consistency between all cells
- Use a grid system (4x4, 3x3, etc.) as the foundation
- Keep overall layout balanced, even with differently sized elements
- Consider how the layout will collapse to a single column on mobile
- Use subtle differences in styling to group related information

---

## Common UI Components

### Modal Dialogs
```
Create a modal dialog component with a header, close button, content area,
and action buttons (Cancel/Confirm). Include a semi-transparent overlay
background and subtle entrance animation. Make it responsive for mobile
with full-width display on small screens.
```

### Action Bars
```
Design an action bar with left-aligned tool buttons (with tooltips on hover)
and right-aligned primary/secondary action buttons. Make it stick to the
top or bottom of the viewport as needed. For mobile, collapse less important
actions into a menu button.
```

### Top Navigation Bars
```
Create a top navigation bar with logo on the left, horizontal navigation
links in center, and user profile/settings on the right. On mobile, collapse
links into a hamburger menu while keeping the logo and profile visible. Add
a subtle shadow and make it fixed at the top of the viewport.
```

### Sidebars
```
Design a collapsible sidebar with logo/brand at top, navigation menu in the
middle, and user settings at bottom. Include highlight states for active
items and subtle hover effects. Make it responsive with slide-in behavior
on mobile.
```

### Inspector Panels
```
Create an inspector panel for editing properties, with collapsible sections,
form controls (inputs, dropdowns, color pickers), and a search filter at
the top. Include a toggle to expand/collapse the panel and make it responsive.
```

### Footers
```
Design a comprehensive footer with company information on the left,
navigation links in the middle columns, and newsletter signup/social media
icons on the right. Include a copyright notice and legal links at the
bottom. Make it stack into a single column on mobile with appropriate spacing.
```

### Component Design Best Practices
- Maintain consistent spacing and sizing across all components
- Consider accessibility with proper contrast and keyboard navigation
- Design for touch targets on mobile (minimum 44px height)
- Create clear visual feedback states (hover, focus, active, disabled)
- Follow platform conventions when appropriate (iOS vs Android patterns)
- Use subtle animations and transitions to improve usability

---

## Device Framing

### Desktop Browser Frame
```
Create a landing page and frame it within a modern browser window with
macOS-style traffic light buttons (red, yellow, green) in the top-left
corner, URL bar, and subtle shadow.
```

### iPhone Frame
```
Design a mobile app screen for a fitness tracker, and place it inside a
modern iPhone 15 Pro frame with the Dynamic Island at the top and status
bar showing full battery and good signal.
```

### iPad Frame
```
Create a tablet version of our dashboard and display it within an iPad Pro
frame with thin bezels, rounded corners, and landscape orientation. Add
subtle environmental shadows.
```

### Laptop Frame
```
Place the website design inside a MacBook Pro frame with the screen at a
slight angle as if viewed from above. Add a wooden desk texture beneath
the laptop.
```

### Desktop Monitor
```
Create a desktop application UI and display it on a sleek monitor with thin
bezels. Add power button and logo at the bottom, with a subtle stand.
```

### Watch Frame
```
Design a fitness app screen for a smartwatch and place it within an Apple
Watch frame with the digital crown and side button visible.
```

### Device Framing Tips
1. **Specify exact device models** — "Frame this in an iPhone 15 Pro" not "put this in a phone frame"
2. **Request contextual elements** — URL bars for browsers, status bars for mobile
3. **Add environmental context** — "Show the iPhone on a wooden desk with soft lighting"
4. **Consider angle and perspective** — "Show the iPad at a slight angle (15°) with a subtle shadow"

### Device Framing Prompt Template
```
Create a [DESIGN TYPE] and place it inside a [SPECIFIC DEVICE MODEL] frame.
Add [CONTEXTUAL ELEMENTS] like status bar and [ENVIRONMENTAL DETAILS] such
as [SURFACE/BACKGROUND]. Position the device at a [ANGLE/PERSPECTIVE] with
[LIGHTING EFFECTS].
```

---

## Layout Prompt Builder Parameters

### Inputs

1. **Layout Type**: RESPONSIVE / LIST / GRID / BENTO / CUSTOM
2. **Content Purpose**: WEBSITE / PRODUCT / DASHBOARD / ARTICLE / PORTFOLIO / MOBILE
3. **Additional Features**: NAVIGATION / HERO / CARDS / FOOTER / SIDEBAR / TABS / GALLERY / FORMS / DARK MODE / ANIMATIONS

### Generated Prompt Example
```
Create a responsive layout for a website with a mobile-first approach.
Include Navigation menu, Hero section.

The layout should stack elements vertically on mobile screens (below 640px)
and expand to a multi-column layout on larger screens. Include a hero section
at the top with a headline on the left and image on the right (stacking
vertically on mobile).

Ensure all spacing and typography scales appropriately across different device
sizes with appropriate breakpoints at 640px, 768px, and 1024px.
```

---

## Practical Examples (Ready-to-Use)

### Landing Page Layout
```
Create a modern landing page layout with the following sections:
1. A hero section at the top with a headline on the left and a feature image
   on the right. On mobile, the image should stack below the headline.
2. A 3-column features section with icons, headings, and brief descriptions
   that becomes a single column on mobile.
3. A testimonial section with a client quote and photo.
4. A call-to-action section with centered text and a prominent signup button.
Use Tailwind CSS with a subtle shadow on cards, rounded corners (8px radius),
and comfortable padding (24px) between sections. Include proper spacing
adjustments for tablet (768px) and mobile (below 640px) breakpoints.
```

### Dashboard Layout
```
Design a dashboard layout with:
1. A fixed sidebar (240px wide) on the left with logo at top, navigation
   links in the middle, and user profile at bottom. On mobile, this
   transforms into a collapsible drawer.
2. A top navigation bar with search input, notifications icon, and settings
   dropdown.
3. Main content area with:
   - A grid of 4 small metric cards (1x1) in the top row
   - A large chart (2x1) below
   - A data table below that
4. Ensure adequate spacing between components (16px) and proper padding
   within cards (16px). Use a clean design with subtle borders (#F0F0F0),
   light gray backgrounds (#F9F9F9) for cards, and a white (#FFFFFF) main
   background. Make it responsive with appropriate stacking on tablet and
   mobile views.
```

### E-commerce Product Page
```
Create an e-commerce product page layout with:
1. A product image gallery on the left (60% width on desktop) with a large
   main image and thumbnails below
2. Product details on the right (40% width) including:
   - Product name (24px, bold)
   - Price and rating
   - Short description
   - Color/size selection options
   - Add to cart button (prominent, full-width)
   - Shipping information
3. A tabbed section below for Description, Specifications, and Reviews
4. Related products grid at the bottom (4 items per row on desktop, 2 on
   tablet, 1 on mobile)
On mobile devices, the layout should stack with the gallery at the top,
followed by product details and other sections. Ensure adequate spacing and
clear visual hierarchy for scanning product information quickly.
```

### Mobile App Screen in Device Frame
```
Design a mobile app screen for a fitness tracking app and place it within
an iPhone 15 Pro frame. The screen should include:
1. A status bar at the top showing full battery, good signal strength, and
   current time (10:30 AM)
2. A dashboard with today's activity progress (steps, calories, distance)
   in card format
3. A circular progress indicator in the center showing daily goal completion
4. Activity history below in a scrollable list with small charts for each day
5. Bottom navigation with icons for Dashboard, Workouts, Nutrition, and Profile
The iPhone frame should be shown at a slight angle (10°) with a subtle drop
shadow. Place it on a gradient background and add a soft reflection beneath
the device for a polished presentation.
```

### Personal Portfolio Bento Layout
```
Create a personal portfolio homepage with a bento box layout with the
following elements:
1. A featured project spanning 2x2 grid cells in the top-left with a project
   image, overlay title, and brief description
2. An about me section (1x1) with a circular profile photo and short bio
3. Skills/tools section (1x2) showing expertise areas with small icons and labels
4. Three smaller project cards (1x1 each) with hover effects that reveal
   project details
5. A contact/social media card (1x1) with icon links
Use consistent spacing (16px gap) between all elements and maintain rounded
corners (12px) throughout. The layout should collapse to a single column on
mobile devices with appropriate stacking order: featured project first, about
me second, then other elements. Include subtle animations for hover states
and transitions.
```

---

## Layout Prompt Best Practices

- Start with a clear overview of the layout structure
- Specify dimensions or proportions where appropriate
- Include responsive behavior for different screen sizes
- Mention spacing, padding, and margins for consistent rhythm
- Define the visual hierarchy and content organization
- Reference specific style guidelines if available (colors, typography, etc.)


