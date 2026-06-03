import 'dart:convert';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/auth_models.dart';

const _keyToken = 'auth_token';
const _keyUser = 'auth_user';

class AuthService {
  final String baseUrl;

  final _googleSignIn = GoogleSignIn(
    scopes: ['email', 'profile'],
    clientId:
        '470638733275-k58682cvnitqo41deodp0a2fk778e6am.apps.googleusercontent.com',
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
    final idToken = auth.idToken;
    if (idToken == null) throw Exception('Google idToken을 가져올 수 없습니다.');

    final resp = await http.post(
      Uri.parse('$baseUrl/api/auth/google'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'id_token': idToken}),
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
}
