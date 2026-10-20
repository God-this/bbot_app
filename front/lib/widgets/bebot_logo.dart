import 'package:flutter/material.dart';

/// BeBot 브랜드 로고 (assets/images/bebot_logo.png).
/// 로고 이미지 자체에 둥근 모서리가 있어 별도 배경 없이 사용한다.
class BebotLogo extends StatelessWidget {
  const BebotLogo({super.key, required this.size});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Image.asset(
      'assets/images/bebot_logo.png',
      width: size,
      height: size,
      filterQuality: FilterQuality.medium,
      semanticLabel: 'BeBot 로고',
    );
  }
}
