namespace MediaBridge.Calling;

public sealed class CallHandlerRegistry
{
    private readonly Dictionary<string, CallHandler> _handlers = new();
    private readonly IServiceProvider _services;

    public CallHandlerRegistry(IServiceProvider services) => _services = services;

    public void RegisterIncomingCall(string callId)
    {
        var factory = _services.GetRequiredService<MediaBridge.Services.OctryxAudioClientFactory>();
        var audioClient = factory.Create(callId);
        var handler = new CallHandler(callId, this, audioClient);
        _handlers[callId] = handler;
        _ = audioClient.ConnectAsync();
        Console.WriteLine($"[CallHandlerRegistry] Registered call {callId}");
    }

    public async Task AnswerCallAsync(string callId)
    {
        if (_handlers.TryGetValue(callId, out var handler))
        {
            await handler.StartAsync("Hello, how can I help you?");
        }
    }

    public void RemoveHandler(string callId)
    {
        if (_handlers.Remove(callId, out var handler))
        {
            handler.Dispose();
            Console.WriteLine($"[CallHandlerRegistry] Removed call {callId}");
        }
    }
}
