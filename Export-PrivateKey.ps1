# 1) Create a new self-signed cert with an exportable private key
$cert = New-SelfSignedCertificate `
  -Subject "CN=EchoMediaAi-Graph" `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -KeyAlgorithm RSA -KeyLength 2048 `
  -KeyExportPolicy Exportable `
  -NotAfter (Get-Date).AddYears(2)

# 2) Export to PFX with password
$pwd = ConvertTo-SecureString -String "EdenEcho!" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath "C:\echomediaai\EchoMediaAi_Graph.pfx" -Password $pwd

# 3) Sanity check: PFX really has the private key and password works
certutil -p "EdenEcho!" -dump "C:\echomediaai\EchoMediaAi_Graph.pfx"
