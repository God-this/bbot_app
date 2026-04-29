import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
// import 'package:flutter_dotenv/flutter_dotenv.dart';

import 'theme.dart';
import 'services/api_service.dart';
import 'services/admin_service.dart';
import 'services/chat_provider.dart';
import 'screens/chat_screen.dart';
import 'screens/admin_dashboard_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // await dotenv.load(fileName: ".env");

  // iOS 스타일 상태바
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarBrightness: Brightness.light,
      statusBarIconBrightness: Brightness.dark,
      statusBarColor: Colors.transparent,
    ),
  );

  runApp(const BeBotApp());
}

class BeBotApp extends StatelessWidget {
  const BeBotApp({super.key});

  @override
  Widget build(BuildContext context) {
    // ──────────────────────────────────────────────
    // 백엔드 서버 URL 설정
    // 개발 환경: http://localhost:8000
    // 배포 환경: 실제 서버 URL로 변경
    // ──────────────────────────────────────────────
    const backendUrl = String.fromEnvironment(
      'BACKEND_URL',
      defaultValue: 'http://localhost:8000',
      // final backendUrl = dotenv.env['BACKEND_URL'] ?? 'http://localhost:8000';
    );

    final apiService = BeBotApiService(baseUrl: backendUrl);
    final adminService = AdminApiService(baseUrl: backendUrl);

    return MultiProvider(
      providers: [
        ChangeNotifierProvider(
          create: (_) => ChatProvider(api: apiService),
        ),
      ],
      child: MaterialApp(
        title: 'BeBot',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.theme,
        home: const ChatScreen(),
        routes: {
          '/admin': (_) =>
              AdminDashboardScreen(adminService: adminService),
        },
      ),
    );
  }
}
