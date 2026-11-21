using MediaBridge.Services;

namespace MediaBridge.Calling;

public sealed class CallHandler : IDisposable
{
    private readonly string _callId;
    private readonly CallHandlerRegistry _registry;
    private readonly OctryxAudioClient _audioClient;
    private readonly CancellationTokenSource _cts = new();
    private Task? _audioTask;

    public CallHandler(string callId, CallHandlerRegistry registry, OctryxAudioClient audioClient)
    {
        _callId = callId;
        _registry = registry;
        _audioClient = audioClient;
    }

    public async Task StartAsync(string thinkingMessage)
    {
        Console.WriteLine($"[CallHandler:{_callId}] Starting");
        _audioTask = Task.Run(() => AudioLoopAsync(thinkingMessage));
    }

    private async Task AudioLoopAsync(string thinkingMessage)
    {
        try
        {
            var greeting = System.Text.Encoding.UTF8.GetBytes(thinkingMessage);
            _audioClient.EnqueueAudio(greeting);

            await foreach (var pcm in _audioClient.ReadAudioAsync(_cts.Token))
            {
                // Received TTS audio from Octryx — send back to Teams
                Console.WriteLine($"[CallHandler:{_callId}] Received {pcm.Length} bytes of TTS audio");
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            Console.WriteLine($"[CallHandler:{_callId}] Audio loop error: {ex.Message}");
        }
        finally
        {
            _registry.RemoveHandler(_callId);
        }
    }

    private static byte[] GenerateSilenceWithSpeech(string message)
    {
        const int sampleRate = 16000;
        const int silenceMs = 300;
        int speechMs = Math.Max(500, message.Length * 60);
        int silenceSamples = (silenceMs * sampleRate) / 1000;
        int speechSamples = (speechMs * sampleRate) / 1000;
        int totalSamples = silenceSamples + speechSamples;
        var pcm = new byte[totalSamples * 2];
        var random = new Random(42);
        for (int i = 0; i < pcm.Length; i++)
            pcm[i] = (byte)random.Next(-100, 100);
        return pcm;
    }

    public void Dispose()
    {
        _cts.Cancel();
        _audioTask?.Dispose();
        _cts.Dispose();
        _audioClient.Dispose();
        Console.WriteLine($"[CallHandler:{_callId}] Disposed");
    }
}
