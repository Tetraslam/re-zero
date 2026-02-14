`default_nettype none

module top_level (
    input wire sysclk_p,
    input wire sysclk_n,

    input wire [4:0] btn,
    input wire [7:0] sw,
    output logic [7:0] led,

    input wire esp_sig_p,
    input wire esp_sig_n
);
    // clk_wiz doesn't work yet idt
    // logic sysclk_200mhz_passthrough;
    // clk_wiz clk_inst (
    //     .sysclk_p(sysclk_p),
    //     .sysclk_n(sysclk_n),
    //     .sysclk_200mhz_passthrough(sysclk_200mhz_passthrough)
    // );

    // TEST SCRIPT
    wire clk_100mhz;
    wire sysclk_locked;

    clkwiz_100mhz sysclk_wiz (
        .sysclk_p   (sysclk_p),
        .sysclk_n   (sysclk_n),
        .clk_100mhz (clk_100mhz),
        .locked     (sysclk_locked)
    );

    logic [25:0] count;

    always_ff @(posedge clk_100mhz) begin
        count <= count + 1;

        if (count == 0) begin
            led <= led + 1;
        end
    end

endmodule
`default_nettype wire
