import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:kakao_flutter_sdk_user/kakao_flutter_sdk_user.dart';

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

  KakaoSdk.init(nativeAppKey: 'e91b61893d56f29bd7f0b52637cbf974');

  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarBrightness: Brightness.light,
      statusBarIconBrightness: Brightness.dark,
      statusBarColor: Colors.transparent,
    ),
  );

  runApp(const BeBotApp());
}

class BeBotApp extends StatefulWidget {
  const BeBotApp({super.key});

  @override
  State<BeBotApp> createState() => _BeBotAppState();
}

class _BeBotAppState extends State<BeBotApp> {
  /// 직전 빌드에서 로그인돼 있던 사용자 ID.
  /// 로그아웃/계정 전환을 감지해 ChatProvider를 초기화하는 데 쓴다.
  int? _lastUserId;

  static const _backendUrl = String.fromEnvironment(
    'BACKEND_URL',
    defaultValue: 'http://localhost:8000',
  );

  late final AuthService     authService  = AuthService(baseUrl: _backendUrl);
  late final BeBotApiService apiService   = BeBotApiService(baseUrl: _backendUrl);
  late final AdminApiService adminService = AdminApiService(baseUrl: _backendUrl);

  @override
  Widget build(BuildContext context) {
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

            // 로그아웃했거나 다른 계정으로 바뀌었으면 이전 사용자의
            // 대화 상태가 화면에 남지 않도록 초기화한다.
            // update()는 빌드 중에 호출되므로 notifyListeners()가
            // 빌드 도중 실행되지 않게 다음 프레임으로 미룬다.
            final userId = auth.user?.userId;
            if (userId != _lastUserId) {
              _lastUserId = userId;
              WidgetsBinding.instance.addPostFrameCallback((_) {
                previous!.reset();
              });
            }
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
