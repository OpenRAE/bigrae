# Terminal authority validation budget

The terminal WebSocket route validates the browser session and the exact range resource before opening, accepting input, or sending output. A native plan can make that complete check exceed the generic five-second socket budget.

Use a finite fifteen-second budget for the terminal route. Keep the existing five-second budget for other routes. An explicit constructor timeout overrides either default, so focused timeout and revocation tests remain fast. The existing thirty-second transport opening deadline remains the outer bound.

Keep every credential, resource, and revocation check. Denial, failure, or timeout closes the socket and discards late scope changes. Do not cache permission decisions. Keep the same shared terminal route expression for both admission and budget selection. This change adds no service, storage, wire field, environment setting, or dependency.

Targeted tests verify route selection, explicit overrides, unchanged opening/input/output checks, timeout refusal, and cleanup on revocation. Live qualification still requires a normal participant shell exchange.
