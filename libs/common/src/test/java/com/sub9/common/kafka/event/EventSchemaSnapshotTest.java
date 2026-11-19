package com.sub9.common.kafka.event;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.fail;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.context.annotation.ClassPathScanningCandidateComponentProvider;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Kafka 이벤트 스키마(필드 이름과 JSON 타입 구조) 스냅샷 테스트.
 *
 * <p>여러 서비스가 같은 이벤트를 주고받으므로, 필드 추가, 삭제, 이름이나 타입 변경은 모두 계약 변경이다.
 * 구조가 바뀌면 이 테스트가 실패하고, 의도한 변경이면 스냅샷을 갱신해 PR diff로 드러낸다.
 *
 * <p>스냅샷 갱신: {@code SCHEMA_SNAPSHOT_UPDATE=true ./gradlew :libs:common:test --tests '*EventSchemaSnapshotTest'}
 * 파일 위치: {@code libs/common/src/test/resources/schema/events/<이벤트>.json}
 */
@DisplayName("Kafka 이벤트 스키마 스냅샷")
class EventSchemaSnapshotTest {

    private static final String EVENT_PACKAGE = "com.sub9.common.kafka.event";
    private static final Path SNAPSHOT_DIR = Path.of("src/test/resources/schema/events");
    private static final boolean UPDATE = "true".equalsIgnoreCase(System.getenv("SCHEMA_SNAPSHOT_UPDATE"));

    private static final JsonMapper MAPPER = new JsonMapper();

    private static final UUID ID_1 = UUID.fromString("00000000-0000-7000-8000-000000000001");
    private static final UUID ID_2 = UUID.fromString("00000000-0000-7000-8000-000000000002");
    private static final Instant AT = Instant.parse("2026-01-01T00:00:00Z");

    /** 이벤트마다 모든 필드가 채워진 대표 샘플. 새 이벤트를 추가하면 여기에 샘플을 추가한다. */
    private static Map<Class<?>, Object> samples() {
        Map<Class<?>, Object> samples = new TreeMap<>((a, b) -> a.getSimpleName().compareTo(b.getSimpleName()));
        samples.put(CategoryCreatedEvent.class, new CategoryCreatedEvent(ID_1));
        samples.put(HashtagCreatedEvent.class, new HashtagCreatedEvent(ID_1));
        samples.put(OrderCanceledEvent.class, new OrderCanceledEvent(ID_1,
                List.of(new OrderCanceledEvent.ProductQuantity(ID_2, 2L))));
        samples.put(OrderNotificationEvent.class, new OrderNotificationEvent(ID_1, "PAYMENT_PAID", "ORDER_SERVICE",
                "ORDER", ID_2, ID_2, "ORD-20260101-0001", "PAID", null, AT));
        samples.put(OrderPaidEvent.class, new OrderPaidEvent(ID_1,
                List.of(new OrderPaidEvent.ProductQuantity(ID_2, 3L))));
        samples.put(ProductCreatedEvent.class, new ProductCreatedEvent(ID_1, ID_2, "상품", "설명", List.of("태그")));
        samples.put(ProductDeletedEvent.class, new ProductDeletedEvent(ID_1, ID_2, AT));
        samples.put(ProductViewSyncEvent.class, new ProductViewSyncEvent(ID_1, LocalDate.parse("2026-01-01"),
                List.of(new ProductViewSyncEvent.ProductViewCount(ID_2, 10L))));
        samples.put(SkuDeletedEvent.class, new SkuDeletedEvent(ID_1, ID_2, AT));
        samples.put(StockRestoreEvent.class, new StockRestoreEvent(ID_1,
                List.of(new StockRestoreEvent.Item(ID_2, 1)), "ORDER_CANCEL"));
        samples.put(UserDeletedEvent.class, new UserDeletedEvent(ID_1, ID_2, AT));
        return samples;
    }

    static Stream<Arguments> events() {
        return samples().entrySet().stream().map(e -> Arguments.of(e.getKey().getSimpleName(), e.getKey(), e.getValue()));
    }

    @Test
    @DisplayName("이벤트 패키지의 모든 이벤트에 스냅샷 샘플이 등록되어 있다")
    void everyEventHasSample() {
        Set<String> declared = scanEventRecords();
        Set<String> sampled = samples().keySet().stream().map(Class::getName).collect(Collectors.toSet());

        assertThat(sampled)
                .withFailMessage("샘플이 없는 이벤트가 있다. EventSchemaSnapshotTest.samples()에 추가한다: %s",
                        declared.stream().filter(name -> !sampled.contains(name)).toList())
                .containsAll(declared);
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("events")
    @DisplayName("이벤트 JSON 구조가 스냅샷과 같다")
    void schemaMatchesSnapshot(String name, Class<?> type, Object sample) throws IOException {
        JsonNode actual = shapeOf(MAPPER.valueToTree(sample));
        Path file = SNAPSHOT_DIR.resolve(name + ".json");

        if (UPDATE) {
            Files.createDirectories(SNAPSHOT_DIR);
            Files.writeString(file, MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(actual) + "\n");
            return;
        }
        if (!Files.exists(file)) {
            fail("스냅샷이 없다: %s. 새 이벤트라면 SCHEMA_SNAPSHOT_UPDATE=true 로 실행해 만들고 함께 커밋한다.", file.toAbsolutePath());
        }
        JsonNode expected = MAPPER.readTree(Files.readString(file));

        assertThat(actual)
                .withFailMessage("""
                        %s 이벤트 스키마가 스냅샷과 다르다(계약 변경).
                        의도한 변경이면 소비자 영향을 확인하고 SCHEMA_SNAPSHOT_UPDATE=true 로 스냅샷을 갱신한다.
                        기대: %s
                        실제: %s""", name, expected, actual)
                .isEqualTo(expected);
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("events")
    @DisplayName("직렬화한 JSON을 같은 이벤트로 복원할 수 있다")
    void roundTrip(String name, Class<?> type, Object sample) {
        String json = MAPPER.writeValueAsString(sample);

        assertThat(MAPPER.readValue(json, type)).isEqualTo(sample);
    }

    /** 값 대신 타입 이름으로 바꾼 구조. 객체는 필드 이름순, 배열은 첫 원소의 구조를 쓴다. */
    private static JsonNode shapeOf(JsonNode node) {
        if (node.isObject()) {
            ObjectNode shape = MAPPER.createObjectNode();
            List<String> names = new ArrayList<>(node.propertyNames());
            names.sort(String::compareTo);
            for (String field : names) {
                shape.set(field, shapeOf(node.get(field)));
            }
            return shape;
        }
        if (node.isArray()) {
            return node.isEmpty() ? MAPPER.createArrayNode() : MAPPER.createArrayNode().add(shapeOf(node.get(0)));
        }
        if (node.isIntegralNumber()) {
            return MAPPER.getNodeFactory().stringNode("integer");
        }
        if (node.isNumber()) {
            return MAPPER.getNodeFactory().stringNode("number");
        }
        if (node.isBoolean()) {
            return MAPPER.getNodeFactory().stringNode("boolean");
        }
        if (node.isNull()) {
            return MAPPER.getNodeFactory().stringNode("null");
        }
        return MAPPER.getNodeFactory().stringNode("string");
    }

    private static Set<String> scanEventRecords() {
        ClassPathScanningCandidateComponentProvider scanner = new ClassPathScanningCandidateComponentProvider(false);
        scanner.addIncludeFilter((reader, factory) -> true);
        return scanner.findCandidateComponents(EVENT_PACKAGE).stream()
                .map(BeanDefinition::getBeanClassName)
                .filter(className -> {
                    try {
                        Class<?> type = Class.forName(className);
                        // 중첩 레코드(예: OrderPaidEvent.ProductQuantity)는 바깥 이벤트의 일부라 제외한다
                        return type.isRecord() && !type.isMemberClass()
                                && type.getPackageName().equals(EVENT_PACKAGE);
                    } catch (ClassNotFoundException e) {
                        return false;
                    }
                })
                .collect(Collectors.toSet());
    }
}
