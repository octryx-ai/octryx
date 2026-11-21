using MediaBridge.Calling;
using MediaBridge.Services;

var builder = WebApplication.CreateBuilder(args);
var config = builder.Configuration;

builder.Services.AddControllers();
builder.Services.AddSingleton<OctryxAudioClientFactory>();
builder.Services.AddSingleton<CallHandlerRegistry>();

var app = builder.Build();

app.MapControllers();
app.MapGet("/", () => "MediaBridge running");

app.Services.GetRequiredService<CallHandlerRegistry>();

Console.WriteLine("[MediaBridge] Starting on http://localhost:8080");
app.Run("http://0.0.0.0:8080");