using System.Net.WebSockets;
using System.Threading.Channels;
using NAudio.Wave;

namespace MediaBridge.Services;

/// <summary>
/// Bidirectional WebSocket client to Octryx audio endpoint.
/// Receives: PCM audio from Teams call (via ngrok) → Octryx STT pipeline.
/// Sends: PCM TTS audio from Octryx → Teams call.
/// </summary>
public sealed class OctryxAudioClient : IDisposable
{
    private readonly string _wsUrl;
    private readonly ClientWebSocket _ws = new();
    private readonly CancellationTokenSource _cts = new();

    private readonly Channel<byte[]> _sendQueue = Channel.CreateBounded<byte[]>(
        new BoundedChannelOptions(200) { FullMode = BoundedChannelFullMode.DropOldest });
    private readonly Channel<byte[]> _recvQueue = Channel.CreateBounded<byte[]>(
        new BoundedChannelOptions(200) { FullMode = BoundedChannelFullMode.Wait });

    public OctryxAudioClient(string wsUrl)
    {
        _wsUrl = wsUrl;
    }

    public async Task ConnectAsync()
    {
        Console.WriteLine($"[OctryxAudioClient] Connecting to {_wsUrl}");
        await _ws.ConnectAsync(new Uri(_wsUrl), _cts.Token);
        Console.WriteLine("[OctryxAudioClient] Connected");
        _ = Task.Run(SendLoopAsync);
        _ = Task.Run(ReceiveLoopAsync);
    }

    public void EnqueueAudio(byte[] pcm) => _sendQueue.Writer.TryWrite(pcm);

    public IAsyncEnumerable<byte[]> ReadAudioAsync(CancellationToken ct = default)
        => _recvQueue.Reader.ReadAllAsync(ct);

    private async Task SendLoopAsync()
    {
        try
        {
            await foreach (var data in _sendQueue.Reader.ReadAllAsync(_cts.Token))
            {
                if (_ws.State != WebSocketState.Open) break;
                await _ws.SendAsync(data, WebSocketMessageType.Binary, true, _cts.Token);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[OctryxAudioClient] Send error: {ex.Message}");
        }
    }

    private async Task ReceiveLoopAsync()
    {
        var buf = new byte[65536];
        try
        {
            while (_ws.State == WebSocketState.Open && !_cts.Token.IsCancellationRequested)
            {
                var result = await _ws.ReceiveAsync(buf, _cts.Token);
                if (result.MessageType == WebSocketMessageType.Close) break;
                if (result.MessageType == WebSocketMessageType.Binary)
                {
                    var decoded = DecodeToPcm(buf.AsMemory(0, result.Count).ToArray());
                    if (decoded.Length > 0)
                        await _recvQueue.Writer.WriteAsync(decoded, _cts.Token);
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[OctryxAudioClient] Receive error: {ex.Message}");
        }
        finally
        {
            _recvQueue.Writer.TryComplete();
        }
    }

    private static byte[] DecodeToPcm(byte[] audioBytes)
    {
        try
        {
            using var ms = new MemoryStream(audioBytes);
            using var reader = new StreamMediaFoundationReader(ms);
            var target = new WaveFormat(16000, 16, 1);
            using var resampler = new MediaFoundationResampler(reader, target);
            using var outMs = new MemoryStream();
            WaveFileWriter.WriteWavFileToStream(outMs, resampler);
            var wav = outMs.ToArray();
            return wav.Length > 44 ? wav[44..] : Array.Empty<byte>();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[OctryxAudioClient] Decode error: {ex.Message}");
            return Array.Empty<byte>();
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        _ws.Dispose();
        _cts.Dispose();
    }
}

public sealed class OctryxAudioClientFactory
{
    private readonly string _baseUrl;

    public OctryxAudioClientFactory(IConfiguration config)
    {
        _baseUrl = config["Octryx:AudioWsBaseUrl"]!.TrimEnd('/');
    }

    public OctryxAudioClient Create(string callId)
    {
        var url = $"{_baseUrl}/{callId}/audio/ws";
        Console.WriteLine($"[OctryxAudioClientFactory] Creating client for {url}");
        return new OctryxAudioClient(url);
    }
}