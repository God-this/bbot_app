import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'theme.dart';
import 'services/api_service.dart';
import 'services/admin_service.dart';
import 'services/auth_service.dart';
import 'services/auth_provider.dart';
import 'services/chat_provider.dart';
import 'screens/login_screen.dart';
import 'screens/chat_screen.dart';
import 'screens/admin_dashboard_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

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
    const backendUrl = String.fromEnvironment(
      'BACKEND_URL',
      defaultValue: 'http://localhost:8000',
    );

    final authService  = AuthService(baseUrl: backendUrl);
    final apiService   = BeBotApiService(baseUrl: backendUrl);
    final adminService = AdminApiService(baseUrl: backendUrl);

    return MultiProvider(
      providers: [
        ChangeNotifierProvider(
          create: (_) => AuthProvider(service: authService)..init(),
        ),
        // AuthProvider 변경 시 apiService / adminService 토큰을 동기화
        ChangeNotifierProxyProvider<AuthProvider, ChatProvider>(
          create: (ctx) {
            final auth = ctx.read<AuthProvider>();
            apiService.setToken(auth.token);
            return ChatProvider(api: apiService, auth: auth);
          },
          update: (_, auth, previous) {
            apiService.setToken(auth.token);
            adminService.setToken(auth.token);
            return previous!;
          },
        ),
      ],
      child: MaterialApp(
        title: 'BeBot',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.theme,
        home: const _AuthGate(),
        routes: {
          '/admin': (ctx) => AdminDashboardScreen(
                adminService: adminService,
              ),
        },
      ),
    );
  }
}

/// 인증 상태에 따라 LoginScreen 또는 ChatScreen을 표시
class _AuthGate extends StatelessWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context) {
    return Consumer<AuthProvider>(
      builder: (context, auth, _) {
        if (auth.isLoading) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        if (auth.isLoggedIn) {
          return const ChatScreen();
        }
        return const LoginScreen();
      },
    );
  }
}
