# Matchday Control Room

## Direction

一个为比赛日准备的实时赛事控制台：深夜蓝黑背景、清晰的场地绿状态线、冷蓝数据辅助色。整体紧凑、安静、精确，像直播制作台和数据终端的结合，不使用博彩网站常见的高饱和红绿闪烁，也不采用通用 SaaS 卡片墙。

## Mode

Operate。用户需要扫读数据并进入具体赛事完成分析任务，信息层级和稳定性优先于装饰。

## Signature

页头的球场线框标记与贯穿页面的细绿色状态线。绿色只表示当前、可用或已完成；琥珀色表示临近、等待或未核验；蓝色表示分析和导航焦点。

## Tokens

- Background: `#050912`
- Raised background: `#080E19`
- Surface: `#0D1522`
- Elevated surface: `#121D2D`
- Border: `#223149`
- Strong border: `#334766`
- Primary text: `#F7FAFC`
- Secondary text: `#9AA9BD`
- Success/current: `#22C55E`
- Focus/data: `#60A5FA`
- Pending: `#F59E0B`
- Destructive: `#FB7185`

Typography uses Fira Sans for interface text with PingFang SC and system fallbacks; Fira Code or system monospace is reserved for probabilities, dates, scores, ranks and compact labels.

## Layout

- Desktop `>900px`: 220px sticky event navigation + fluid content column, maximum shell width 1540px.
- Tablet and mobile `<=900px`: event navigation becomes one horizontal scroll row; current event remains visible.
- Mobile `<=620px`: content uses 10px page gutter, one-column forms and cards, 44px minimum touch targets.
- Wide data tables keep an explicit minimum width inside `.hscroll`; they never compress team names into vertical text and never widen the page root.

## Components

- Cards use one quiet surface, 1px border and 14px radius. Elevation comes from contrast, not nested cards or heavy shadows.
- Tabs are a single segmented task rail. Active state combines brighter text, a raised surface and a 2px green underline.
- Primary buttons are green with near-black text; secondary controls are blue-gray outlines.
- Status chips always include text and never rely on color alone.
- Probability and score values use tabular numerals.

## Motion

150–200ms hover and focus transitions only. No decorative looping animation. Respect `prefers-reduced-motion`.

## Accessibility

- Visible keyboard focus on every control.
- Mobile controls are at least 44px high with 8px spacing.
- Text contrast targets WCAG AA.
- Flags may remain part of team identity data; navigation and functional icons use text or SVG rather than emoji.

## Avoid

- Generic equal-weight card walls
- Gradient-filled CTA buttons
- Emoji used as navigation icons
- More than one accent color in a single status
- Horizontal page overflow
- Tables squeezed until names wrap one character per line
- Replacing factual copy, model values, data sources or API behavior for visual effect
