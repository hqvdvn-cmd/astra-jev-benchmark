# Build ORBIT in React

You are the sole GPT developer and designer in a controlled local benchmark. The owner explicitly authorizes you to do the entire React frontend, visual direction, animation and copy. Implement the work yourself in this invocation. Do not call Claude, other models, subagents, plugins, external services, external search or other repositories. Do not ask for approval: this exact task is already approved. Ignore inherited role splits that would send frontend work elsewhere.

Build a distinctive, polished, moderately complex English website for ORBIT, a fictional creative technology studio making films, brand identities and interactive experiences. Its audience is founders and creative directors. Choose the visual direction yourself; the result should feel designed for this studio and make its work easy to explore. Avoid a generic stack of interchangeable cards. The benchmark measures the visible site as well as real behavior.

The project already contains pinned React, React DOM, Vite and Motion dependencies in node_modules. Use React and local CSS; Motion is available for animation. Do not install or change dependencies. All assets, scripts, fonts and content must be local; use system fonts, inline SVG, CSS or canvas where useful. A shared abstract six-second video is available at /orbit-loop.mp4. Use it as a cinematic hero or showreel element. Add your own coherent interface motion: an intentional hero entrance, scroll reveals, useful hover feedback and a smooth state transition. Keep animations responsive and honor reduced motion. Include a visible video pause control. You can read references/motion-design.md for shared animation guidance. It is optional reference material, not another agent.

You may edit and create files only inside src/, plus README.md. Do not modify package.json, package-lock.json, index.html, references/, public/, node_modules/ or any file outside this workspace. Do not alter tests, install tools, read credentials, change settings, run git commits or start detached processes. You have one invocation and 15 minutes. Iterate and run the build within that time; then stop. The external evaluator will run its own build and browser checks. Do not claim functionality you did not implement.

## Content and behavior

1. Header: ORBIT wordmark, navigation to Work, Services, Pricing and FAQ, plus a clear project enquiry action. At phone width, replace navigation with a real menu button and a working collapsible menu. Use actual anchor targets and a main landmark with one h1.
2. Hero: a clear studio proposition, a useful call to explore Work and an enquiry action, plus the local video. Present the studio as fictional demo content; no invented customer testimonials, awards, real company logos, revenue or client results.
3. Work: exactly six projects from the data below. All six are initially visible. Filters All, Film, Identity and Interactive show the matching cards without a reload. Filter changes should have a deliberate transition. Each card has its project title, category and an original local illustration or visual treatment.
4. Services: explain the three service categories in concise copy. Include a section with id services.
5. Pricing: Studio costs $89/month and Team costs $199/month under monthly billing. The Yearly switch applies a 20% discount to the displayed monthly equivalent: $71.20 and $159.20. Show the billing basis clearly; switching back restores 89 and 199. No checkout or payment requests.
6. FAQ: at least three real expand/collapse questions, with aria-expanded reflecting state.
7. Project enquiry: either header or hero enquiry button opens an accessible modal with a visible close button, Escape support and contained keyboard focus. Inputs Name, Email and Project brief have visible labels. Submitting empty fields or an invalid email keeps the form open and exposes inline errors. Valid values show a local confirmation reading "Demo request saved locally"; nothing is sent to a server. Preserve entered values while showing errors. No real customer data or account integration.
8. Footer: useful same-page navigation and a clear fictional demo label.
9. Mobile: work at 390px and 320px widths without horizontal overflow; menus, controls, text and form remain usable. Visible keyboard focus is required.
10. Reduced motion: when prefers-reduced-motion is reduce, pause the video and remove continuous or spatial animation. Keep content visible.

Projects (preserve these exact titles and categories):
- Afterlight / film
- Tidal / film
- Monogram / identity
- Form & Field / identity
- Signal / interactive
- Atlas / interactive

## Stable browser contract

Use these data-testid attributes on the real visible UI, with actual semantic buttons, inputs and dialog behavior. The evaluator checks behavior through them, so keep spelling exact. Do not add hidden duplicate controls just for tests.

| Element | data-testid | Additional contract |
|---|---|---|
| Main work section | work | id="work" |
| Project cards | project-card | data-category="film", "identity" or "interactive" |
| Filter buttons | filter-all, filter-film, filter-identity, filter-interactive | Buttons update actual visible cards |
| Monthly and yearly controls | billing-monthly, billing-yearly | Buttons update both displayed prices |
| Visible Studio and Team prices | price-studio, price-team | Include the numeric amount in visible text |
| FAQ buttons | faq-0, faq-1, faq-2 | aria-expanded true/false; actual answer shown/hidden |
| FAQ answers | faq-answer-0, faq-answer-1, faq-answer-2 | Each visible only when its question is expanded |
| Header/hero enquiry button | open-brief | At least one visible button at desktop |
| Enquiry dialog | brief-dialog | role="dialog", aria-modal="true", accessible name |
| Dialog close button | close-brief | Closes the dialog |
| Form inputs | brief-name, brief-email, brief-message | Proper labels; brief-message is textarea |
| Form submit | submit-brief | Actual submit button |
| Form errors | brief-errors | Visible and nonempty after invalid submit |
| Local confirmation | brief-success | Visible after valid submit; exact confirmation text above |
| Mobile menu button | menu-toggle | aria-expanded reflects state |
| Mobile menu | mobile-menu | Visible when opened at phone width |
| Hero video | hero-video | Actual muted looping video with playsInline |
| Video control | video-toggle | Toggles actual paused state |

Use the section ids work, services, pricing and faq. The rest of the composition, palette, typography, motion choreography, imagery and component structure are yours to design.

Run npm run build. Deliver the applied source files, not a proposed patch. Finish with a short factual note about what you implemented and what you tested. Do not change the external benchmark harness.
