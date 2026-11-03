"""Small SigV4 client for the disposable local object store."""

import datetime
import hashlib
import hmac
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from providers import require


class LocalS3:
    def __init__(self, endpoint, access, secret):
        parsed = urllib.parse.urlsplit(endpoint)
        require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and not parsed.username and not parsed.query and not parsed.fragment,
                "s3_endpoint_not_local")
        self.endpoint, self.access, self.secret = endpoint, access, secret

    def request(self, method, path, query="", body=b""):
        now = datetime.datetime.now(datetime.timezone.utc)
        date, stamp = now.strftime("%Y%m%d"), now.strftime("%Y%m%dT%H%M%SZ")
        payload = hashlib.sha256(body).hexdigest()
        headers = {"host": urllib.parse.urlsplit(self.endpoint).netloc,
                   "x-amz-content-sha256": payload, "x-amz-date": stamp}
        names = ";".join(sorted(headers))
        canonical = "\n".join([method, path, query,
                              "".join(f"{name}:{headers[name]}\n" for name in sorted(headers)),
                              names, payload])
        scope = f"{date}/us-east-1/s3/aws4_request"
        text = "\n".join(["AWS4-HMAC-SHA256", stamp, scope,
                           hashlib.sha256(canonical.encode()).hexdigest()])
        key = ("AWS4" + self.secret).encode()
        for part in (date, "us-east-1", "s3", "aws4_request"):
            key = hmac.new(key, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
        headers["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={self.access}/{scope}, "
                                    f"SignedHeaders={names}, Signature={signature}")
        request = urllib.request.Request(self.endpoint + path + ("?" + query if query else ""),
                                         data=body if method == "PUT" else None,
                                         headers=headers, method=method)
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as response:
            return response.read(), response.headers

    def keys(self, bucket):
        body, _ = self.request("GET", "/" + bucket, "list-type=2")
        listing = ET.fromstring(body)
        require(listing.findtext("{*}IsTruncated") != "true", "s3_listing_truncated")
        return [element.text for element in listing.findall(".//{*}Key")]
