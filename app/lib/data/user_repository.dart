import 'authed_api.dart';

class Me {
  const Me({required this.id, required this.alias, required this.karma});

  final String id;
  final String alias;
  final int karma;

  factory Me.fromJson(Map<String, dynamic> json) => Me(
    id: json['id'] as String,
    alias: json['alias'] as String,
    karma: json['karma'] as int,
  );
}

class UserRepository {
  UserRepository({required this._api});

  final AuthedApi _api;

  Future<Me> me() async => Me.fromJson(await _api.get('/me'));
}
