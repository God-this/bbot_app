import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:google_sign_in/google_sign_in.dart';
import 'package:flutter_naver_login/flutter_naver_login.dart';
import 'package:flutter_naver_login/interface/types/naver_login_status.dart';
import 'package:kakao_flutter_sdk_user/kakao_flutter_sdk_user.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../models/auth_models.dart';

const _keyToken = 'auth_token';
const _keyUser = 'auth_user';
const _keyGuestDeviceId = 'guest_device_id';
const _keyNaverOAuthState = 'naver_oauth_state';
const _keyKakaoOAuthState = 'kakao_oauth_state';

const _naverClientId    = 'QsJhbwfPiRXPAGESm8qG';
const _naverRedirectUri = String.fromEnvironment(
  'NAVER_REDIRECT_URI',
  defaultValue: 'https://bebot.co.kr/auth/naver/callback',
);
const _kakaoRestApiKey  = '4a06e82b5323e19aa16203aa074999b4';
const _kakaoRedirectUri = String.fromEnvironment(
  'KAKAO_REDIRECT_URI',
  defaultValue: 'https://bebot.co.kr/auth/kakao/callback',
);

class AuthService {
  final String baseUrl;

  final _googleSignIn = GoogleSignIn(
    scopes: ['email', 'profile'],
    clientId: kIsWeb
        ? '470638733275-cud88egkutov2ls7hq2uivlu9ieb2ic5.apps.googleusercontent.com'
        : '470638733275-k58682cvnitqo41deodp0a2fk778e6am.apps.googleusercontent.com',
    // 수정
    serverClientId: kIsWeb
        ? null
        : '470638733275-k58682cvnitqo41deodp0a2fk778e6am.apps.googleusercontent.com',
  );

  AuthService({required this.baseUrl});

  // ── 저장된 인증 정보 불러오기 ───────────────────────────────────

  Future<String?> getStoredToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyToken);
  }

  Future<UserInfo?> getStoredUser() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_keyUser);
    if (raw == null) return null;
    try {
      return UserInfo.fromMap(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<void> _saveAuth(String token, UserInfo user) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyToken, token);
    await prefs.setString(_keyUser, jsonEncode(user.toMap()));
  }

  Future<void> clearAuth() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyToken);
    await prefs.remove(_keyUser);
    try {
      await _googleSignIn.signOut();
    } catch (_) {}
    try {
      await FlutterNaverLogin.logOutAndDeleteToken();
    } catch (_) {}
    try {
      await UserApi.instance.logout();
    } catch (_) {}
  }

  // ── Google 로그인 → 백엔드 JWT 발급 ───────────────────────────

  Future<({String token, UserInfo user})?> signInWithGoogle() async {
    final account = await _googleSignIn.signIn();
    if (account == null) return null; // 사용자가 취소

    final auth = await account.authentication;

    // 웹은 signIn() 팝업 플로우에서 idToken이 null이므로 accessToken 사용
    final Map<String, String> tokenBody;
    if (kIsWeb) {
      final accessToken = auth.accessToken;
      if (accessToken == null) throw Exception('Google accessToken을 가져올 수 없습니다.');
      tokenBody = {'access_token': accessToken};
    } else {
      final idToken = auth.idToken;
      if (idToken == null) throw Exception('Google idToken을 가져올 수 없습니다.');
      tokenBody = {'id_token': idToken};
    }

    final resp = await http.post(
      Uri.parse('$baseUrl/api/auth/google'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(tokenBody),
    );

    if (resp.statusCode != 200) {
      throw Exception('서버 로그인 실패 (${resp.statusCode})');
    }

    final data =
        jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final token = data['access_token'] as String;
    final user = UserInfo.fromMap(data);

    await _saveAuth(token, user);
    return (token: token, user: user);
  }

  // ── 게스트 로그인 → 백엔드 JWT 발급 ───────────────────────────

  /// 로컬에 저장된 device UUID를 반환하거나, 없으면 새로 생성해 저장합니다.
  /// 같은 device_id를 계속 재사용해야 앱 재실행 시에도 같은 게스트로 인식됩니다.
  Future<String> _getOrCreateGuestDeviceId() async {
    final prefs = await SharedPreferences.getInstance();
    var deviceId = prefs.getString(_keyGuestDeviceId);
    if (deviceId == null) {
      deviceId = const Uuid().v4();
      await prefs.setString(_keyGuestDeviceId, deviceId);
    }
    return deviceId;
  }

  Future<({String token, UserInfo user})> signInAsGuest() async {
    final deviceId = await _getOrCreateGuestDeviceId();

    final resp = await http.post(
      Uri.parse('$baseUrl/api/auth/guest'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'device_id': deviceId}),
    );

    if (resp.statusCode != 200) {
      throw Exception('게스트 로그인 실패 (${resp.statusCode})');
    }

    final data =
        jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final token = data['access_token'] as String;
    final user = UserInfo.fromMap(data);

    await _saveAuth(token, user);
    return (token: token, user: user);
  }

  // ── Naver 로그인 (모바일: 네이티브 SDK) → 백엔드 JWT 발급 ───────

  Future<({String token, UserInfo user})?> signInWithNaver() async {
    final result = await FlutterNaverLogin.logIn();

    if (result.status != NaverLoginStatus.loggedIn) {
      return null; // 사용자가 취소했거나 실패
    }

    final accessToken = result.accessToken?.accessToken ?? '';
    if (accessToken.isEmpty) {
      throw Exception('네이버 accessToken을 가져올 수 없습니다.');
    }

    final resp = await http.post(
      Uri.parse('$baseUrl/api/auth/naver'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'access_token': accessToken}),
    );

    if (resp.statusCode != 200) {
      throw Exception('서버 로그인 실패 (${resp.statusCode})');
    }

    final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final token = data['access_token'] as String;
    final user = UserInfo.fromMap(data);

    await _saveAuth(token, user);
    return (token: token, user: user);
  }

  // ── Naver 로그인 (웹: 브라우저 리다이렉트) ──────────────────────

  String _generateRandomState() {
    final rand = Random.secure();
    return List.generate(16, (_) => rand.nextInt(16).toRadixString(16)).join();
  }

  /// 웹: 네이버 로그인 페이지로 현재 탭을 리다이렉트합니다. (여기서 함수 실행은 끝남)
  Future<void> startNaverWebLogin() async {
    final state = _generateRandomState();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyNaverOAuthState, state);

    final uri = Uri.https('nid.naver.com', '/oauth2.0/authorize', {
      'response_type': 'code',
      'client_id':     _naverClientId,
      'redirect_uri':  _naverRedirectUri,
      'state':         state,
    });

    await launchUrl(uri, webOnlyWindowName: '_self');
  }

  /// 웹: 콜백 페이지로 돌아왔을 때 code를 백엔드로 넘겨 JWT를 발급받습니다.
  Future<({String token, UserInfo user})?> completeNaverWebLogin({
    required String code,
    required String state,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    final savedState = prefs.getString(_keyNaverOAuthState);
    await prefs.remove(_keyNaverOAuthState);

    if (savedState == null || savedState != state) {
      throw Exception('네이버 로그인 상태값이 일치하지 않습니다. 다시 시도해 주세요.');
    }

    final resp = await http.post(
      Uri.parse('$baseUrl/api/auth/naver/web'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'code':         code,
        'state':        state,
        'redirect_uri': _naverRedirectUri,
      }),
    );

    if (resp.statusCode != 200) {
      throw Exception('서버 로그인 실패 (${resp.statusCode})');
    }

    final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final token = data['access_token'] as String;
    final user = UserInfo.fromMap(data);

    await _saveAuth(token, user);
    return (token: token, user: user);
  }

  // ── Kakao 로그인 → 백엔드 JWT 발급 ───────────────────────────

  Future<({String token, UserInfo user})?> signInWithKakao() async {
    String accessToken;
    try {
      final installed = await isKakaoTalkInstalled();
      final token = installed
          ? await UserApi.instance.loginWithKakaoTalk()
          : await UserApi.instance.loginWithKakaoAccount();
      accessToken = token.accessToken;
    } catch (e) {
      try {
        final token = await UserApi.instance.loginWithKakaoAccount();
        accessToken = token.accessToken;
      } catch (_) {
        return null; // 사용자 취소 또는 완전 실패
      }
    }

    final resp = await http.post(
      Uri.parse('$baseUrl/api/auth/kakao'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'access_token': accessToken}),
    );

    if (resp.statusCode != 200) {
      throw Exception('서버 로그인 실패 (${resp.statusCode})');
    }

    final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final token = data['access_token'] as String;
    final user = UserInfo.fromMap(data);

    await _saveAuth(token, user);
    return (token: token, user: user);
  }

  /// 웹: 카카오 로그인 페이지로 현재 탭을 리다이렉트합니다. (여기서 함수 실행은 끝남)
  Future<void> startKakaoWebLogin() async {
    final uri = Uri.https('kauth.kakao.com', '/oauth/authorize', {
      'response_type': 'code',
      'client_id':     _kakaoRestApiKey,
      'redirect_uri':  _kakaoRedirectUri,
    });

    await launchUrl(uri, webOnlyWindowName: '_self');
  }

  /// 웹: 콜백 페이지로 돌아왔을 때 code를 백엔드로 넘겨 JWT를 발급받습니다.
  Future<({String token, UserInfo user})?> completeKakaoWebLogin({
    required String code,
  }) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/auth/kakao/web'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'code':         code,
        'redirect_uri': _kakaoRedirectUri,
      }),
    );

    if (resp.statusCode != 200) {
      throw Exception('서버 로그인 실패 (${resp.statusCode})');
    }

    final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final token = data['access_token'] as String;
    final user = UserInfo.fromMap(data);

    await _saveAuth(token, user);
    return (token: token, user: user);
  }
}