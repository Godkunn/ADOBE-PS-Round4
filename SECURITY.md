# Security & Passive Auditing Policy

## 1. Non-Destructive Operational Guarantee
The **Brand AI-Readiness Audit** package is strictly **Recommend-Only / Read-Only**:
- All network operations use HTTP `GET` or `HEAD` methods.
- The system never issues state-altering HTTP methods (`POST`, `PUT`, `DELETE`, `PATCH`).
- No forms are submitted, no authentication cookies are injected, and no active exploits or vulnerability fuzzing are conducted.

---

## 2. Privacy & Data Handling
- **Zero PII Collection:** The auditor parses only publicly exposed web markup, schema metadata, and robots/sitemap directives. No user data, passwords, or personal identifying information is stored or transmitted.
- **No Third-Party AI/LLM API Calls:** All parsing is deterministic and local (Regex, BeautifulSoup, JSON-LD extraction). No target data is sent to OpenAI, Anthropic, Google, or any external third-party API service during execution.

---

## 3. Network Hygiene & Politeness
- **Respect for Server Load:** Each audit performs a minimal request footprint (1 main page fetch + 1 robots.txt fetch + 1 sitemap fetch).
- **Timeouts & Deadlock Prevention:** Strict 10-second request timeouts are enforced on all network calls.
- **User-Agent Transparency:** All inspection requests declare explicit, standard User-Agent headers.

---

## 4. SSRF Defense & Target Validation
- **Loopback & Shorthand Rejection:** Prohibits `127.0.0.0/8`, `::1`, `localhost`, and BSD shorthand representations (`0`, `127.1`, `0x7f000001`, octal).
- **Private & Non-Global Network Filtering:** Blocks RFC 1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), Carrier-Grade NAT (`100.64.0.0/10`), link-local (`169.254.0.0/16`), and benchmarking ranges (`198.18.0.0/15`).
- **Redirect SSRF Containment:** Validates every redirect hop dynamically with `is_safe_target_url()` to eliminate open-redirect SSRF attack vectors.
- **Pre-Flight DNS Resolution Guard:** Resolves target hostnames to socket IPs and validates all returned A and AAAA addresses prior to HTTP dispatch.
