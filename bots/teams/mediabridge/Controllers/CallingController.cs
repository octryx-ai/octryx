using Microsoft.AspNetCore.Mvc;
using MediaBridge.Calling;

[ApiController]
[Route("api/calling")]
public class CallingController : ControllerBase
{
    private readonly CallHandlerRegistry _registry;
    private readonly ILogger<CallingController> _logger;

    public CallingController(CallHandlerRegistry registry, ILogger<CallingController> logger)
    {
        _registry = registry;
        _logger = logger;
    }

    [HttpPost("incoming")]
    public async Task<IActionResult> HandleIncomingCall()
    {
        try
        {
            using var reader = new StreamReader(Request.Body);
            var body = await reader.ReadToEndAsync();
            _logger.LogInformation("Incoming call webhook: {Body}", body);

            // Extract callId from the Bot Framework call notification payload
            string? callId = null;
            try
            {
                var doc = System.Text.Json.JsonDocument.Parse(body);
                var root = doc.RootElement;
                // Bot Framework wraps call info in "value" → "id"
                if (root.TryGetProperty("value", out var val) && val.TryGetProperty("id", out var idProp))
                    callId = idProp.GetString();
                // Fallback: top-level "id"
                if (callId == null && root.TryGetProperty("id", out var topId))
                    callId = topId.GetString();
            }
            catch { /* payload may not be JSON or structure differs */ }

            if (callId != null)
            {
                _logger.LogInformation("Registering call {CallId} from webhook", callId);
                _registry.RegisterIncomingCall(callId);
                await _registry.AnswerCallAsync(callId);
                return Ok(new { status = "answered", callId });
            }

            _logger.LogWarning("Could not extract callId from incoming call payload");
            return Ok(new { status = "received_no_callid" });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error handling incoming call");
            return StatusCode(500);
        }
    }

    [HttpPost("register-call")]
    public async Task<IActionResult> RegisterCall([FromBody] RegisterCallRequest request)
    {
        try
        {
            _logger.LogInformation("Registering call {CallId}", request.CallId);
            _registry.RegisterIncomingCall(request.CallId);
            if (request.AutoAnswer)
            {
                await _registry.AnswerCallAsync(request.CallId);
            }
            return Ok(new { status = "registered" });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error registering call");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    [HttpDelete("call/{callId}")]
    public IActionResult RemoveCall(string callId)
    {
        _registry.RemoveHandler(callId);
        return Ok(new { status = "removed" });
    }

    [HttpGet("health")]
    public IActionResult Health() => Ok(new { status = "healthy" });
}

public record RegisterCallRequest(string CallId, bool AutoAnswer = true);