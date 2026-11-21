<?php
// Webmail com Login Único (OAuth2/OIDC via Keycloak).
// O navegador vai a localhost:8080; o servidor fala com keycloak:8080 pela rede interna.
$config['language'] = 'pt_PT';
$config['product_name'] = 'Correio Institucional do Estado (DEMO)';
$config['oauth_provider'] = 'generic';
$config['oauth_provider_name'] = 'Login Único do Estado';
$config['oauth_client_id'] = 'webmail';
$config['oauth_client_secret'] = getenv('WEBMAIL_CLIENT_SECRET');
$config['oauth_auth_uri'] = 'http://localhost:8080/realms/estado/protocol/openid-connect/auth';
$config['oauth_token_uri'] = 'http://keycloak:8080/realms/estado/protocol/openid-connect/token';
$config['oauth_identity_uri'] = 'http://keycloak:8080/realms/estado/protocol/openid-connect/userinfo';
$config['oauth_scope'] = 'openid email profile';
$config['oauth_identity_fields'] = ['email'];
$config['oauth_login_redirect'] = false;
$config['smtp_user'] = '%u';
$config['smtp_pass'] = '%p';
