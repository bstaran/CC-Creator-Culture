package com.sub9.orderservice.order.application.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.groups.Tuple.tuple;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.then;

import com.sub9.common.identifier.UuidV7Generator;
import com.sub9.common.kafka.event.OrderCanceledEvent;
import com.sub9.common.kafka.topic.KafkaTopics;
import com.sub9.orderservice.order.application.port.output.PaymentCancellationPort;
import com.sub9.orderservice.order.application.port.output.StockPort.RestoreReason;
import com.sub9.orderservice.order.domain.model.Money;
import com.sub9.orderservice.order.domain.model.Order;
import com.sub9.orderservice.order.domain.model.OrderItem;
import com.sub9.orderservice.order.domain.model.ProductSnapshot;
import com.sub9.orderservice.order.domain.model.ShippingAddress;
import com.sub9.orderservice.order.domain.repository.OrderRepository;
import com.sub9.orderservice.order.infrastructure.outbox.OrderEventOutboxWriter;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
@DisplayName("주문 취소 트랜잭션 서비스")
class OrderCancellationTransactionServiceTest {

    private static final Instant CREATED_AT = Instant.parse("2026-09-04T00:00:00Z");
    private static final Instant CANCELED_AT = Instant.parse("2026-09-04T00:10:00Z");

    @Mock
    private OrderRepository orderRepository;

    @Mock
    private PaymentCancellationPort paymentCancellationPort;

    @Mock
    private OrderCommandIdempotencyService idempotencyService;

    @Mock
    private OrderEventOutboxWriter outbox;

    private OrderCancellationTransactionService cancellationService;

    @BeforeEach
    void setUp() {
        cancellationService = new OrderCancellationTransactionService(
                orderRepository,
                new UuidV7Generator(),
                paymentCancellationPort,
                idempotencyService,
                Clock.fixed(CANCELED_AT, ZoneOffset.UTC),
                outbox);
    }

    @Nested
    @DisplayName("주문을 취소하면")
    class Cancel {

        @Test
        @DisplayName("order.canceled 이벤트의 상품별 수량을 상품 기준으로 합산해 주문 ID 키로 쓴다")
        void cancelOrderSumsQuantitiesByProduct() {
            UUID productA = uuid(500);
            UUID productB = uuid(501);
            Order order = paidOrder(
                    10,
                    item(11, productA, uuid(600), 2),
                    item(12, productB, uuid(601), 4),
                    item(13, productA, uuid(602), 3));
            given(orderRepository.findByOrderNumberForUpdate(order.getOrderNumber()))
                    .willReturn(Optional.of(order));

            cancellationService.cancel(order.getCustomerId(), uuid(900), order.getOrderNumber());

            ArgumentCaptor<Object> eventCaptor = ArgumentCaptor.forClass(Object.class);
            then(outbox).should().write(
                    eq(KafkaTopics.ORDER_CANCELED), eq(order.getId().toString()), eventCaptor.capture());
            OrderCanceledEvent event = (OrderCanceledEvent) eventCaptor.getValue();
            assertThat(event.orderId()).isEqualTo(order.getId());
            assertThat(event.productQuantities())
                    .extracting(OrderCanceledEvent.ProductQuantity::productId,
                            OrderCanceledEvent.ProductQuantity::quantity)
                    .containsExactlyInAnyOrder(
                            tuple(productA, 5L),
                            tuple(productB, 4L));
        }

        @Test
        @DisplayName("재고 복구 명령은 주문 항목 순서 그대로 SKU와 수량을 담고 사유는 ORDER_CANCEL이다")
        void cancelOrderReturnsStockRestoreInItemOrder() {
            Order order = paidOrder(
                    20,
                    item(21, uuid(500), uuid(600), 2),
                    item(22, uuid(501), uuid(601), 4),
                    item(23, uuid(500), uuid(602), 3));
            given(orderRepository.findByOrderNumberForUpdate(order.getOrderNumber()))
                    .willReturn(Optional.of(order));

            var canceled = cancellationService.cancel(
                    order.getCustomerId(), uuid(900), order.getOrderNumber());

            assertThat(canceled.stockRestore().orderId()).isEqualTo(order.getId());
            assertThat(canceled.stockRestore().reason()).isEqualTo(RestoreReason.ORDER_CANCEL);
            assertThat(canceled.stockRestore().items())
                    .extracting(stockItem -> stockItem.skuId(), stockItem -> stockItem.quantity())
                    .containsExactly(
                            tuple(uuid(600), 2),
                            tuple(uuid(601), 4),
                            tuple(uuid(602), 3));
            then(outbox).should().write(eq(KafkaTopics.ORDER_NOTIFICATION), eq(order.getId().toString()), any());
        }
    }

    private static Order paidOrder(long sequence, OrderItem... items) {
        Order order = Order.create(
                uuid(sequence),
                uuid(sequence + 1_000),
                ShippingAddress.of(
                        "홍길동", "010-1234-5678", "06236", "서울특별시 강남구", "101호"),
                List.of(items),
                CREATED_AT);
        order.markPaid(CREATED_AT.plusSeconds(60));
        return order;
    }

    private static OrderItem item(long sequence, UUID productId, UUID skuId, int quantity) {
        return OrderItem.create(
                uuid(sequence), null,
                uuid(sequence + 2_000),
                productId,
                skuId,
                null,
                ProductSnapshot.of("아크릴 스탠드", "A 타입", Money.won(18_000), quantity),
                Money.won(0));
    }

    private static UUID uuid(long sequence) {
        return UUID.fromString("0198f2a0-76c0-7000-8000-%012x".formatted(sequence));
    }
}
