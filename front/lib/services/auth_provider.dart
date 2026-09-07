import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import '../models/auth_models.dart';
import 'auth_service.dart';

enum AuthStatus { unknown, authenticated, unauthenticated }

class AuthProvider extends ChangeNotifier {
  final AuthService _service;

  AuthStatus _status = AuthStatus.unknown;
  UserInfo?  _user;
  String?    _token;
  String?    _error;

  AuthProvider({required AuthService service}) : _service = service;

  AuthStatus get status    => _status;
  UserInfo?  get user      => _user;
  String?    get token     => _token;
  String?    get error     => _error;
  bool get isLoading        => _status == AuthStatus.unknown;
  bool get isLoggedIn       => _status == AuthStatus.authenticated;
  bool get isGuest          => _user?.role != 'admin' && (_token != null) && (_user?.email.isEmpty ?? false);

  /// 앱 시작 시 저장된 토큰 확인
  Future<void> init() async {
    // 웹: 네이버 로그인 후 콜백 URL로 돌아온 상태인지 먼저 확인
    if (kIsWeb) {
      final handledNaver = await _tryCompleteNaverWebCallback();
      if (handledNaver) return;
    }

    final token = await _service.getStoredToken();
    final user  = await _service.getStoredUser();
    if (token != null && user != null) {
      _token  = token;
      _user   = user;
      _status = AuthStatus.authenticated;
    } else {
      _status = AuthStatus.unauthenticated;
    }
    notifyListeners();
  }

  Future<void> signIn() async {
    _error = null;
    try {
      final result = await _service.signInWithGoogle();
      if (result != null) {
        _token  = result.token;
        _user   = result.user;
        _status = AuthStatus.authenticated;
        notifyListeners();
      }
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 로그인 없이 게스트로 계속하기
  Future<void> continueAsGuest() async {
    _error = null;
    try {
      final result = await _service.signInAsGuest();
      _token  = result.token;
      _user   = result.user;
      _status = AuthStatus.authenticated;
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 네이버 로그인 — 모바일은 네이티브 SDK, 웹은 페이지 리다이렉트
  Future<void> signInWithNaver() async {
    _error = null;
    try {
      if (kIsWeb) {
        await _service.startNaverWebLogin(); // 페이지 리다이렉트, 이후 처리는 init()에서
        return;
      }
      final result = await _service.signInWithNaver();
      if (result != null) {
        _token  = result.token;
        _user   = result.user;
        _status = AuthStatus.authenticated;
        notifyListeners();
      }
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 웹 전용: 네이버 콜백 URL로 돌아왔을 때 code를 처리
  Future<bool> _tryCompleteNaverWebCallback() async {
    final uri = Uri.base;
    if (!uri.path.contains('/auth/naver/callback')) return false;

    final code  = uri.queryParameters['code'];
    final state = uri.queryParameters['state'];
    if (code == null || state == null) return false;

    try {
      final result = await _service.completeNaverWebLogin(code: code, state: state);
      if (result != null) {
        _token  = result.token;
        _user   = result.user;
        _status = AuthStatus.authenticated;
        notifyListeners();
        return true;
      }
    } catch (e) {
      _error = e.toString();
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    }
    return false;
  }

  Future<void> signOut() async {
    await _service.clearAuth();
    _token  = null;
    _user   = null;
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  /// 401 응답 시 호출 — 토큰 만료 처리
  Future<void> onUnauthorized() async {
    await _service.clearAuth();
    _token  = null;
    _user   = null;
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }
}