// `default_nettype none

// /**
// Allow debugging of what is in the delay line by UART transmit.
// */
// module uart_tds_out (
//     input wire clk,
//     input wire rst,  // replace w/ your system reset
//     output logic uart_txd,
//     output logic input_debug_full,

//     // tds delay debug lines
//     input wire [63:0] tds_delay_trace,
//     input wire tds_delay_valid
// );
//   localparam int MAX_CHUNKS_PER_LINE = 8;

//   // state
//   typedef enum {
//     IDLE = 0,
//     WAIT_FOR_FIFO
//   } tds_delay_state;
//   tds_delay_state state;
//   tds_delay_state next_state;

//   // internal state
//   logic [7:0] curr_chunk;

//   // modules (for chunking up input)
//   logic input_debug_empty;
//   logic [63:0] input_to_send_out;
//   logic [63:0] shifted_input_to_send_out;
//   command_fifo #(
//       .DEPTH(128),
//       .WIDTH(64)
//   ) input_debug_fifo (
//       .clk(clk),
//       .rst(rst),

//       .full(input_debug_full),  // output: is fifo full?
//       .empty(input_debug_empty),  // output: is fifo empty? (0 entries in fifo)

//       // WRITE TO FIFO
//       .write(tds_delay_valid),  // input: din valid?
//       .command_in(tds_delay_trace),  // data to be written to fifo

//       // READ FROM FIFO
//       .command_out(input_to_send_out),  // read out data
//       // .read(state == IDLE && !input_debug_empty)  // input: ready to read
//       .read((state == WAIT_FOR_FIFO) && (curr_chunk == 0))
//   );

//   logic uart_ready_for_next_byte;
//   assign uart_ready_for_next_byte = (!uart_busy && !uart_fifo_empty);
//   logic uart_trigger;

//   // rising-edge-trigger creates a single pulse:
//   rising_edge_trigger edge_pulser (
//       .clk(clk),
//       .rst(rst),
//       .signal(uart_ready_for_next_byte),
//       .edge_signal(uart_trigger)
//   );

//   logic uart_trigger_fifo_write_valid;
//   assign uart_trigger_fifo_write_valid = uart_fifo_write_valid;

//   // modules (for sending to uart)
//   logic uart_fifo_full;
//   logic uart_fifo_empty;
//   logic uart_fifo_write_valid;
//   logic [7:0] uart_fifo_write_data;
//   logic [7:0] uart_tx_out;
//   logic uart_busy;

//   command_fifo #(
//       .DEPTH(1024),
//       .WIDTH(8)
//   ) uart_fifo (
//       .clk(clk),
//       .rst(rst),

//       .full (uart_fifo_full),  // output: is fifo full?
//       .empty(uart_fifo_empty), // output: is fifo empty? (0 entries in fifo)

//       // WRITE TO FIFO
//       .write(uart_trigger_fifo_write_valid),  // input: din valid?
//       .command_in(uart_fifo_write_data),  // data to be written to fifo

//       // READ FROM FIFO
//       .command_out(uart_tx_out),  // read out data
//       .read(uart_trigger)  // input: ready to read
//   );

//   uart_transmit #(
//       .INPUT_CLOCK_FREQ(240_000_000),
//       .BAUD_RATE(9600)
//   ) transmit_inst (
//       .clk(clk),
//       .rst(rst),
//       .din(uart_tx_out),
//       .trigger(uart_trigger),  // if not empty, valid data for uart
//       .busy(uart_busy),
//       .dout(uart_txd)
//   );

//   // state action
//   always_ff @(posedge clk) begin
//     if (rst) begin
//       state                     <= IDLE;
//       curr_chunk                <= 0;
//       uart_fifo_write_valid     <= 0;
//       uart_fifo_write_data      <= 0;
//       shifted_input_to_send_out <= 0;
//     end else begin
//       case (state)
//         IDLE: begin
//           curr_chunk <= 0;
//           uart_fifo_write_valid <= 0;
//           uart_fifo_write_data <= 0;
//           shifted_input_to_send_out <= input_to_send_out;
//           state <= tds_delay_state'(!input_debug_empty ? WAIT_FOR_FIFO : IDLE);
//         end
//         WAIT_FOR_FIFO: begin
//           uart_fifo_write_valid <= 0;
//           state <= tds_delay_state'(curr_chunk >= MAX_CHUNKS_PER_LINE ? IDLE : WAIT_FOR_FIFO);

//           if (!uart_fifo_full && (curr_chunk < MAX_CHUNKS_PER_LINE)) begin
//             uart_fifo_write_valid     <= 1;
//             // send MSB first
//             uart_fifo_write_data      <= shifted_input_to_send_out[63:56];
//             shifted_input_to_send_out <= shifted_input_to_send_out << 8;
//             curr_chunk                <= curr_chunk + 1;
//           end
//         end
//       endcase
//     end
//   end

// endmodule
// `default_nettype wire

`default_nettype none

module uart_tds_out (
    input wire clk,
    input wire rst,
    output logic uart_txd,
    output logic input_debug_full,

    input wire [63:0] tds_delay_trace,
    input wire tds_delay_valid
);
  localparam int MAX_CHUNKS_PER_LINE = 8;

  typedef enum {
    IDLE = 0,
    READ_FIFO,
    WAIT_FOR_FIFO
  } tds_delay_state;
  tds_delay_state state;

  logic [7:0] curr_chunk;
  logic input_debug_empty;
  logic [63:0] input_to_send_out;
  logic [63:0] shifted_input_to_send_out;
  
  command_fifo #(
      .DEPTH(2048),
      .WIDTH(64)
  ) input_debug_fifo (
      .clk(clk),
      .rst(rst),
      .full(input_debug_full),
      .empty(input_debug_empty),
      .write(tds_delay_valid),
      .command_in(tds_delay_trace),
      .command_out(input_to_send_out),
      .read(state == READ_FIFO)
  );

  logic uart_fifo_full;
  logic uart_fifo_empty;
  logic uart_fifo_write_valid;
  logic [7:0] uart_fifo_write_data;
  logic [7:0] uart_tx_out;
  logic uart_busy;

  command_fifo #(
      .DEPTH(1024),
      .WIDTH(8)
  ) uart_fifo (
      .clk(clk),
      .rst(rst),
      .full (uart_fifo_full),
      .empty(uart_fifo_empty),
      .write(uart_fifo_write_valid),
      .command_in(uart_fifo_write_data),
      .command_out(uart_tx_out),
      .read(!uart_busy && !uart_fifo_empty)
  );

  uart_transmit #(
      .INPUT_CLOCK_FREQ(240_000_000),
      .BAUD_RATE(250_000)
  ) transmit_inst (
      .clk(clk),
      .rst(rst),
      .din(uart_tx_out),
      .trigger(!uart_busy && !uart_fifo_empty),
      .busy(uart_busy),
      .dout(uart_txd)
  );

  always_ff @(posedge clk) begin
    if (rst) begin
      state                     <= IDLE;
      curr_chunk                <= 0;
      uart_fifo_write_valid     <= 0;
      uart_fifo_write_data      <= 0;
      shifted_input_to_send_out <= 0;
    end else begin
      case (state)
        IDLE: begin
          curr_chunk            <= 0;
          uart_fifo_write_valid <= 0;
          
          if (!input_debug_empty) begin
            state <= READ_FIFO;
          end
        end
        
        READ_FIFO: begin
          shifted_input_to_send_out <= input_to_send_out;
          state                     <= WAIT_FOR_FIFO;
        end
        
        WAIT_FOR_FIFO: begin
          uart_fifo_write_valid <= 0;
          
          if (curr_chunk >= MAX_CHUNKS_PER_LINE) begin
            state <= IDLE;
          end else if (!uart_fifo_full) begin
            uart_fifo_write_valid     <= 1;
            // Send LSB byte first (bits [7:0], then [15:8], etc.)
            uart_fifo_write_data      <= shifted_input_to_send_out[7:0];
            shifted_input_to_send_out <= shifted_input_to_send_out >> 8;  // Right shift
            curr_chunk                <= curr_chunk + 1;
          end
        end
      endcase
    end
  end

endmodule
`default_nettype wire