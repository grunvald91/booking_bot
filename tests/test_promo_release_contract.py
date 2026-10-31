"""Exact vhost rewrite contract: never touch unrelated Nginx hosts."""
import pytest
from scripts.deploy_servgo_promo_monitor import nginx_promo_transform


ORIGINAL = """
server {
    listen 443 ssl;
    server_name promo.servgo.ru;
    location /static/ { proxy_pass http://127.0.0.1:8080/static/; }
    location / { proxy_pass http://127.0.0.1:8080/; }
}
server {
    listen 80;
    server_name promo.servgo.ru;
    return 301 https://$host$request_uri;
}
"""


def test_rewrites_only_two_promo_upstreams_and_keeps_other_directives():
    new = nginx_promo_transform(ORIGINAL)
    assert new.count("127.0.0.1:18080/") == 2
    assert "127.0.0.1:8080/" not in new
    assert "return 301 https://$host$request_uri;" in new
    assert nginx_promo_transform(new) == new


@pytest.mark.parametrize("invalid", [
    ORIGINAL.replace("promo.servgo.ru;", "example.org;", 1),
    ORIGINAL.replace("127.0.0.1:8080", "127.0.0.1:8000", 1),
    ORIGINAL + "\nserver { server_name another.example; }",
    ORIGINAL.replace("location /static/", "location /cached/"),
])
def test_refuses_unknown_or_mixed_nginx_layouts(invalid):
    with pytest.raises(ValueError):
        nginx_promo_transform(invalid)
