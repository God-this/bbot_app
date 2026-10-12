/// 로그인 후 백엔드에서 반환되는 사용자 정보 모델
class UserInfo {
  final int userId;
  final String email;
  final String nickname;
  final String role;
  /// 로그인 제공자: google / naver / kakao / guest
  final String provider;

  const UserInfo({
    required this.userId,
    required this.email,
    required this.nickname,
    required this.role,
    this.provider = '',
  });

  factory UserInfo.fromMap(Map<String, dynamic> map) => UserInfo(
        userId:     map['user_id']     as int?    ?? 0,
        email:      map['email']       as String? ?? '',
        nickname:   map['nickname']    as String? ?? '',
        role:       map['role']        as String? ?? 'user',
        provider:   map['provider']    as String? ?? '',
      );

  Map<String, dynamic> toMap() => {
        'user_id':     userId,
        'email':       email,
        'nickname':    nickname,
        'role':        role,
        'provider':    provider,
      };

  bool get isAdmin => role == 'admin';
  bool get isGuest => provider == 'guest';
}