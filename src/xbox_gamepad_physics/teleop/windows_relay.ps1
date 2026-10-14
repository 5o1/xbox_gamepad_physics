param([Parameter(Mandatory=$true)][int]$ListenPort,[string]$WslAddress,[Parameter(Mandatory=$true)][int]$WslPort)
$ErrorActionPreference='Stop'
# Session-local TCP relay only: no registry, firewall, route or service changes.
$listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$ListenPort)
$listener.Start()
$connections=New-Object 'System.Collections.Generic.List[object]'
try {
  while($true) {
    if($listener.Pending()) {
      $client=$listener.AcceptTcpClient()
      $client.NoDelay=$true
      $upstream=[Net.Sockets.TcpClient]::new()
      $upstream.NoDelay=$true
      $upstream.Connect($WslAddress,$WslPort)
      $a=$client.GetStream().CopyToAsync($upstream.GetStream())
      $b=$upstream.GetStream().CopyToAsync($client.GetStream())
      $connections.Add(@{client=$client;upstream=$upstream;a=$a;b=$b})
    }
    foreach($entry in @($connections.ToArray())) {
      if($entry.a.IsCompleted -or $entry.b.IsCompleted) {
        $entry.client.Close();$entry.upstream.Close();$null=$connections.Remove($entry)
      }
    }
    Start-Sleep -Milliseconds 5
  }
} finally {
  foreach($entry in $connections){$entry.client.Close();$entry.upstream.Close()}
  $listener.Stop()
}
