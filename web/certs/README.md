# HTTPS Certificates for Web Voice Picking

Browsers require HTTPS for microphone access on non-localhost addresses.
When workers open the page on their phones (over LAN), you need SSL certificates.

## Option 1: mkcert (recommended)

Creates a trusted local CA — no browser warnings.

```bash
# Install mkcert
brew install mkcert        # macOS
# or: sudo apt install mkcert  # Linux

# Create and install the local CA (one-time)
mkcert -install

# Find your server LAN IP
ifconfig | grep "inet "    # look for 192.168.x.x

# Generate certificate for your IP
cd web/certs
mkcert 192.168.1.100       # replace with your actual IP
# Creates: 192.168.1.100.pem and 192.168.1.100-key.pem
```

### Trust on phones (one-time per phone):

Find the CA root certificate:
```bash
mkcert -CAROOT
# Copy rootCA.pem from that directory
```

**iOS:**
1. AirDrop or email the `rootCA.pem` file to the phone
2. Open it — go to Settings > General > VPN & Device Management
3. Install the profile
4. Go to Settings > General > About > Certificate Trust Settings
5. Enable trust for the mkcert CA

**Android:**
1. Copy `rootCA.pem` to the phone
2. Settings > Security > Install from storage (or Encryption & credentials > Install a certificate)

## Option 2: Self-signed certificate (simpler setup, browser warning)

```bash
cd web/certs
openssl req -x509 -newkey rsa:2048 \
    -keyout key.pem -out cert.pem \
    -days 365 -nodes \
    -subj "/CN=192.168.1.100" \
    -addext "subjectAltName=IP:192.168.1.100"
```

Workers will see a browser warning and must tap "Advanced" > "Proceed" to accept.

## Configure the server

Set environment variables:
```bash
export SSL_CERTFILE=web/certs/192.168.1.100.pem
export SSL_KEYFILE=web/certs/192.168.1.100-key.pem
```

Or add to `.env`:
```
SSL_CERTFILE=web/certs/192.168.1.100.pem
SSL_KEYFILE=web/certs/192.168.1.100-key.pem
```

Then start the server:
```bash
python -m web
```

Workers open: `https://192.168.1.100:8443`
