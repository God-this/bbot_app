/// 로그인 후 백엔드에서 반환되는 사용자 정보 모델
class UserInfo {
  final int userId;
  final String email;
  final String nickname;
  final String profileImg;
  final String role;

  const UserInfo({
    required this.userId,
    required this.email,
    required this.nickname,
    required this.profileImg,
    required this.role,
  });

  factory UserInfo.fromMap(Map<String, dynamic> map) => UserInfo(
        userId:     map['user_id']     as int?    ?? 0,
        email:      map['email']       as String? ?? '',
        nickname:   map['nickname']    as String? ?? '',
        profileImg: map['profile_img'] as String? ?? '',
        role:       map['role']        as String? ?? 'user',
      );

  Map<String, dynamic> toMap() => {
        'user_id':     userId,
        'email':       email,
        'nickname':    nickname,
        'profile_img': profileImg,
        'role':        role,
      };

  bool get isAdmin => role == 'admin';
}
