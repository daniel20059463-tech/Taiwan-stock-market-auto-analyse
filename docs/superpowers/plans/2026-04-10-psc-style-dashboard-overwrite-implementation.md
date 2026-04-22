# PSC-Style Dashboard Overwrite Implementation Plan

- Update dashboard tests to assert the new terminal labels and top bars first.
- Rework Dashboard.tsx into a PSC-style layout with two header bars and a two-column terminal body.
- Replace the market pane cards with a dense quote table while preserving selection and sorting.
- Keep the chart logic intact but embed it into the new right-top chart module.
- Move trade timeline and positions into a left-bottom terminal pane.
- Move price structure, technical levels, and account summary into a right-bottom terminal pane.
- Ensure the root and each pane use viewport-safe sizing with internal overflow only.
- Run targeted tests, then full frontend tests, then build.
