import 'dart:convert';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../models/auth_models.dart';

const _keyToken = 'auth_token';
const _keyUser = 'auth_user';
const _keyGuestDeviceId = 'guest_device_id';

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
}