---
title: REST API calls
---

The audit of every REST API call, from agents and from test calls: one row per call.

### What you see
- **User** and **Workspace**: who asked, and where.
- **Status**: *Succeeded*, *Refused* (Octryx stopped it before or instead of sending, e.g. no grant or outside the
  scope) or *Failed* (the API or the network failed).
- **Kept / dropped**: records returned, and records the result filter dropped as outside the scope.
- **Applied scope**: the role that allowed the call and the fixed values and filter Octryx applied.

### Next steps
- [Back to REST APIs](/chat?area=admin&tab=restApis)

### Good to know
Every call runs as the connection's technical account. Secrets and answers are never stored in the audit.
