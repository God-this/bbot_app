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

  /// 앱 시작 시 저장된 토큰 확인
  Future<void> init() async {
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
